from django.contrib import admin
from .models import Movie, Theater, Showtime, Seat, Booking, SeatReservation



@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'genre', 'language']
    search_fields = ['name', 'cast']
    list_filter = ['genre', 'language']

@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'location']
    search_fields = ['name', 'location']


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['seat_number', 'theater', 'row']
    list_filter = ['theater', 'row']
    search_fields = ['seat_number']



@admin.register(Showtime)
class ShowtimeAdmin(admin.ModelAdmin):
    list_display = ['movie', 'theater', 'start_time']
    list_filter = ['movie', 'theater']
    ordering = ['start_time']


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'seat', 'showtime', 'amount', 'status', 'booked_at']
    list_filter = ['status', 'showtime', 'booked_at']
    search_fields = ['user__username', 'seat__seat_number', 'payment_id']
    readonly_fields = ['booked_at']


@admin.register(SeatReservation)
class SeatReservationAdmin(admin.ModelAdmin):
    list_display = ['user', 'seat', 'showtime', 'status', 'reserved_until']
    list_filter = ['status', 'showtime']
    search_fields = ['user__username', 'seat__seat_number']
    readonly_fields = ['reserved_until']