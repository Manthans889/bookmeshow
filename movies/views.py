from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.utils import timezone
from datetime import date, timedelta
from django.http import JsonResponse, HttpResponseBadRequest

from .models import Movie, Theater, Seat, Booking, Showtime, SeatReservation

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


import json
import hmac
import hashlib
from django.conf import settings
from .razorpay_client import client
from django.contrib.auth.models import User
from django.http import  HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .tasks import send_booking_confirmation
from .analytics import (
    get_revenue, get_popular_movies, get_busiest_theaters,
    get_peak_hours, get_cancellation_rate, get_revenue_chart
)

def movie_list(request):
    movies = Movie.objects.all()

    search = request.GET.get('search', '').strip()
    genre = request.GET.get('genre', '').strip()
    language = request.GET.get('language', '').strip()

    if search:
        movies = movies.filter(
            Q(name__icontains=search) |
            Q(cast__icontains=search) |
            Q(description__icontains=search)
        )

    if genre:
        movies = movies.filter(genre=genre)

    if language:
        movies = movies.filter(language=language)

    return render(request, 'movies/movie_list.html', {
        'movies': movies,
        'genres': Movie.GENRE_CHOICES,
        'languages': Movie.LANGUAGE_CHOICES,
        'search_query': search,
        'selected_genre': genre,
        'selected_language': language,
    })



def theater_list(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)

    today = date.today()
    week_dates = [today + timedelta(days=i) for i in range(7)]

    selected_date = request.GET.get("date")
    if selected_date:
        selected_date = date.fromisoformat(selected_date)
    else:
        selected_date = today

    showtimes = Showtime.objects.filter(
        movie=movie,
        start_time__date=selected_date
    ).select_related('theater')

    return render(request, 'movies/theater_list.html', {
        'movie': movie,
        'showtimes': showtimes,
        'week_dates': week_dates,
        'selected_date': selected_date,
    })



def details(request, movie_id):
    movie = get_object_or_404(Movie, pk=movie_id)
    return render(request, 'movies/details.html', {'movie': movie})



@login_required(login_url='/login/')
def seat_selection(request, showtime_id):
    showtime = get_object_or_404(Showtime, id=showtime_id)

    seats = Seat.objects.filter(theater=showtime.theater)

    # Already booked seats
    booked_seats = Booking.objects.filter(
        showtime=showtime,
        status='confirmed'
    ).values_list('seat_id', flat=True)

    
    reserved_seats = SeatReservation.objects.filter(
        showtime=showtime,
        status='reserved',
        reserved_until__gt=timezone.now()
    ).exclude(user=request.user).values_list('seat_id', flat=True)

    return render(request, 'movies/seat_selection.html', {
        'showtime': showtime,
        'seats': seats,
        'booked_seat_ids': list(booked_seats),
        'reserved_seat_ids': list(reserved_seats),
    })



@login_required(login_url='/login/')
def create_order(request, showtime_id):
    if request.method != 'POST':
        return HttpResponseBadRequest()

    data = json.loads(request.body)
    selected_seats = data.get('seats', [])

    if not selected_seats:
        return JsonResponse({'error': 'No seats selected'}, status=400)

    showtime = get_object_or_404(Showtime, id=showtime_id)

    locked = []
    unavailable = []

    for seat_id in selected_seats:
        try:
            with transaction.atomic():
                seat = Seat.objects.select_for_update().get(id=seat_id)

                
                if Booking.objects.filter(
                    seat=seat,
                    showtime=showtime,
                    status='confirmed'
                ).exists():
                    unavailable.append(seat.seat_number)
                    continue

                
                conflict = SeatReservation.objects.filter(
                    seat=seat,
                    showtime=showtime,
                    status='reserved',
                    reserved_until__gt=timezone.now()
                ).exclude(user=request.user).exists()

                if conflict:
                    unavailable.append(seat.seat_number)
                    continue

            
                SeatReservation.objects.update_or_create(
                    seat=seat,
                    user=request.user,
                    showtime=showtime,
                    defaults={
                        'reserved_until': timezone.now() + timedelta(minutes=2),
                        'status': 'reserved'
                    }
                )

                locked.append(seat_id)

        except Seat.DoesNotExist:
            unavailable.append(str(seat_id))

    if unavailable:
        SeatReservation.objects.filter(
            seat_id__in=locked,
            user=request.user
        ).update(status='expired')

        return JsonResponse({'error': f"Unavailable: {', '.join(unavailable)}"}, status=409)

    
    total_amount = int(150 * len(selected_seats) * 100)

    order = client.order.create({
    'amount': total_amount,
    'currency': 'INR',
    'payment_capture': 1,
    'notes': {
        'showtime_id': showtime_id,
        'user_id': request.user.id,
        'seats': ','.join(selected_seats),
    }
})
    request.session['pending_seats'] = selected_seats
    request.session['pending_showtime'] = showtime_id

    return JsonResponse({
        'order_id': order['id'],
        'amount': total_amount,
        'key_id': settings.RAZORPAY_KEY_ID,
    })
# Check this again hmac causing error 
@login_required(login_url='/login/')
def verify_payment(request):
    if request.method != 'POST':
        return HttpResponseBadRequest()

    data = json.loads(request.body)

    order_id = data.get('razorpay_order_id')
    payment_id = data.get('razorpay_payment_id')
    signature = data.get('razorpay_signature')

    msg = f"{order_id}|{payment_id}"
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        return JsonResponse({'error': 'Invalid signature'}, status=400)

    selected_seats = request.session.get('pending_seats', [])
    showtime_id = request.session.get('pending_showtime')
    showtime = get_object_or_404(Showtime, id=showtime_id)

    booked = []

    for seat_id in selected_seats:
        try:
            with transaction.atomic():
                seat = Seat.objects.select_for_update().get(id=seat_id)

                reservation = SeatReservation.objects.filter(
                    seat=seat,
                    user=request.user,
                    showtime=showtime,
                    status='reserved',
                    reserved_until__gt=timezone.now()
                ).first()

                if not reservation:
                    continue

                # prevent duplicate booking per seat
                if Booking.objects.filter(seat=seat, showtime=showtime).exists():
                    continue

                Booking.objects.create(
                    user=request.user,
                    seat=seat,
                    showtime=showtime,
                    payment_id=payment_id,
                    amount=showtime.price,  # ✅ use dynamic price
                    status='confirmed'
                )

                reservation.status = 'confirmed'
                reservation.save()

                booked.append(seat.seat_number)

        except Exception as e:
            print("BOOKING ERROR:", str(e))
            continue

    # 📧 Send email only if something booked
    if booked:
        booking_data = {
            'user_email': request.user.email,
            'user_name': request.user.get_full_name() or request.user.username,
            'movie_name': showtime.movie.name,
            'theater_name': showtime.theater.name,
            'showtime': showtime.start_time.strftime('%d %b %Y, %I:%M %p'),
            'seat_number': ', '.join(booked),
            'amount': str(showtime.price * len(booked)),
            'payment_id': payment_id,
        }
        # send_booking_confirmation.delay(booking_data) --- celery in render needs purchase tier , SO  fallback email
        try:
            subject = f"Booking Confirmed — {booking_data['movie_name']}"

            html_body = render_to_string(
                'movies/emails/booking_confirmation.html',
                {'booking': booking_data}
            )

            text_body = (
                f"Hi {booking_data['user_name']}, your booking is confirmed!\n"
                f"Movie: {booking_data['movie_name']}\n"
                f"Theater: {booking_data['theater_name']}\n"
                f"Show: {booking_data['showtime']}\n"
                f"Seats: {booking_data['seat_number']}\n"
                f"Amount: ₹{booking_data['amount']}\n"
                f"Payment ID: {booking_data['payment_id']}\n"
            )

            email = EmailMultiAlternatives(
                subject,
                text_body,
                settings.DEFAULT_FROM_EMAIL,
                [booking_data['user_email']]
            )

            email.attach_alternative(html_body, 'text/html')
            email.send(fail_silently=True)

            print("EMAIL SENT")

        except Exception as e:
            print("EMAIL ERROR:", str(e))

    request.session.flush()

    return JsonResponse({'status': 'confirmed', 'seats': booked})

@login_required(login_url='/login/')
def release_seats(request):
    selected_seats = request.session.get('pending_seats', [])

    SeatReservation.objects.filter(
        seat_id__in=selected_seats,
        user=request.user,
        status='reserved'
    ).update(status='expired')

    request.session.flush()

    return JsonResponse({'status': 'released'})

@csrf_exempt
def payment_success(request):
    if request.method != "POST":
        return HttpResponse("Invalid request")

    try:
        payment_id = request.POST.get('razorpay_payment_id')
        order_id = request.POST.get('razorpay_order_id')
        signature = request.POST.get('razorpay_signature')

        msg = f"{order_id}|{payment_id}"
        expected = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            msg.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            return HttpResponse("Invalid signature")

        order = client.order.fetch(order_id)
        notes = order.get('notes', {})

        showtime = get_object_or_404(Showtime, id=notes.get('showtime_id'))
        user = get_object_or_404(User, id=notes.get('user_id'))
        seat_ids = notes.get('seats', '').split(',')

        booked = []  #In booking modules they are appearing so no problem in them

        for seat_id in seat_ids:
            if not seat_id:
                continue

            try:
                with transaction.atomic():
                    seat = Seat.objects.select_for_update().get(id=seat_id)

                    # prevent duplicate booking
                    if Booking.objects.filter(seat=seat, showtime=showtime).exists():
                       continue

                    Booking.objects.create(
                        user=user,
                        seat=seat,
                        showtime=showtime,
                        payment_id=payment_id,
                        amount=150,
                        status='confirmed'
                    )

                    booked.append(seat.seat_number)

            except Exception:
                continue
            
        print("BOOKED:", booked)
        # 🔥🔥 ADD THIS BLOCK (THIS IS WHAT YOU WERE MISSING)
        if booked:
            from .tasks import send_booking_confirmation
            print("CALLING EMAIL TASK")
    
            booking_data = {
                'user_email': user.email,
                'user_name': user.get_full_name() or user.username,
                'movie_name': showtime.movie.name,
                'theater_name': showtime.theater.name,
                'showtime': showtime.start_time.strftime('%d %b %Y, %I:%M %p'),
                'seat_number': ', '.join(booked),
                'amount': str(150 * len(booked)),
                'payment_id': payment_id,
            }
            if not user.email:
              print("❌ User has no email:", user.username)
            else:
             send_booking_confirmation.delay(booking_data)
            

        return HttpResponse("Payment success ✅")

    except Exception as e:
        print("ERROR:", str(e))  
        return HttpResponse("Something broke ❌")



@csrf_exempt
def razorpay_webhook(request):
    if request.method != 'POST':
        return HttpResponseBadRequest()

    webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    received_sig = request.headers.get('X-Razorpay-Signature')
    payload = request.body

    expected_sig = hmac.new(
        webhook_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, received_sig):
        return JsonResponse({'error': 'Invalid signature'}, status=400)

    event = json.loads(payload)
    event_type = event.get('event')

    if event_type == 'payment.captured':
        payment = event['payload']['payment']['entity']
        payment_id = payment['id']

        
        if Booking.objects.filter(payment_id=payment_id).exists():
            return JsonResponse({'status': 'already processed'})

        notes = payment.get('notes', {})
        showtime_id = notes.get('showtime_id')
        user_id = notes.get('user_id')
        seat_ids = notes.get('seats', '').split(',')

        showtime = Showtime.objects.get(id=showtime_id)
        user = User.objects.get(id=user_id)

        for seat_id in seat_ids:
            if not seat_id:
                continue

            try:
                with transaction.atomic():
                    seat = Seat.objects.select_for_update().get(id=seat_id)

                    Booking.objects.create(
                        user=user,
                        seat=seat,
                        showtime=showtime,
                        payment_id=payment_id,
                        amount=150,
                        status='confirmed'
                    )

            except Exception:
                continue
        
        if seat_ids:
            booking_data = {
        'user_email': user.email,
        'user_name': user.get_full_name() or user.username,
        'movie_name': showtime.movie.name,
        'theater_name': showtime.theater.name,
        'showtime': showtime.start_time.strftime('%d %b %Y, %I:%M %p'),
        'seat_number': ', '.join(seat_ids),
        'amount': str(150 * len(seat_ids)),
        'payment_id': payment_id,
    }

    send_booking_confirmation.delay(booking_data)

    return JsonResponse({'status': 'ok'})

# REMOVED LOGIN REQUIRED FOR WEIRD ERROR : ADD AGAIN 
def admin_dashboard(request):
    
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect('/login/')

    context = {
        'revenue_daily':   get_revenue('daily'),
        'revenue_weekly':  get_revenue('weekly'),
        'revenue_monthly': get_revenue('monthly'),
        'popular_movies':  get_popular_movies(),
        'busiest_theaters': get_busiest_theaters(),
        'peak_hours':      get_peak_hours(),
        'cancellation_rate': get_cancellation_rate(),
        'revenue_chart':   get_revenue_chart(),
        'total_bookings':  Booking.objects.filter(status='confirmed').count(),
    }
    return render(request, 'movies/admin_dashboard.html', context)