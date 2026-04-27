from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from urllib.parse import urlparse, parse_qs


class Movie(models.Model):

    GENRE_CHOICES = [
        ('ACTION', 'Action'),
        ('COMEDY', 'Comedy'),
        ('DRAMA', 'Drama'),
        ('THRILLER', 'Thriller'),
        ('ROMANCE', 'Romance'),
        ('HORROR', 'Horror'),
        ('SCI-FI', 'Science Fiction'),
    ]

    LANGUAGE_CHOICES = [
        ('hindi', 'Hindi'),
        ('english', 'English'),
        ('tamil', 'Tamil'),
        ('telugu', 'Telugu'),
    ]

    name = models.CharField(max_length=255)
    image = models.URLField(blank=True, null=True)
    rating = models.DecimalField(max_digits=3, decimal_places=1)
    cast = models.TextField()
    description = models.TextField(blank=True, null=True)

    genre = models.CharField(max_length=50, choices=GENRE_CHOICES)
    language = models.CharField(max_length=50, choices=LANGUAGE_CHOICES)

    trailer_url = models.URLField(blank=True, null=True)

    def get_trailer_id(self):
        if not self.trailer_url:
            return None

        url = urlparse(self.trailer_url)

        if "youtube.com" in url.netloc:
            query = parse_qs(url.query)
            if "v" in query:
                return query["v"][0]

        if "youtu.be" in url.netloc:
            return url.path.strip("/")

        return None

    def get_embed_url(self):
        video_id = self.get_trailer_id()
        if video_id:
            return f"https://www.youtube-nocookie.com/embed/{video_id}?rel=0"
        return None

    def __str__(self):
        return self.name



class Theater(models.Model):
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        
        if is_new:
            self.create_default_seats()

    def create_default_seats(self):
        seats = []
        for row in ['A', 'B', 'C', 'D']:   
            for num in range(1, 6):        
                seats.append(Seat(
                    theater=self,
                    seat_number=f"{row}{num}",
                    row=row
                ))
        Seat.objects.bulk_create(seats)

    def __str__(self):
        return self.name



class Seat(models.Model):
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, related_name="seats")
    seat_number = models.CharField(max_length=10)
    row = models.CharField(max_length=5, blank=True)

    class Meta:
        unique_together = ['theater', 'seat_number']

    def __str__(self):
        return f"{self.seat_number} - {self.theater.name}"


class Showtime(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="showtimes")
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, related_name="showtimes")
    start_time = models.DateTimeField()
    price = models.DecimalField(max_digits=6, decimal_places=2)
    def __str__(self):
        return f"{self.movie.name} @ {self.theater.name} ({self.start_time})"


class Booking(models.Model):
    STATUS_CHOICES = [
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled')
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE)
    showtime = models.ForeignKey(Showtime, on_delete=models.CASCADE)

    booked_at = models.DateTimeField(auto_now_add=True)
    payment_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    amount = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')

    class Meta:
        unique_together = ['seat', 'showtime']

    def __str__(self):
        return f"{self.user.username} - {self.seat.seat_number} - {self.showtime}"



class SeatReservation(models.Model):
    STATUS_CHOICES = [
        ('reserved', 'Reserved'),
        ('confirmed', 'Confirmed'),
        ('expired', 'Expired'),
    ]

    seat = models.ForeignKey(Seat, on_delete=models.CASCADE, related_name='reservations')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    showtime = models.ForeignKey(Showtime, on_delete=models.CASCADE)

    reserved_until = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='reserved')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['seat', 'showtime'],
                condition=models.Q(status='reserved'),
                name='unique_active_reservation'
            )
        ]

    def is_active(self):
        return self.status == 'reserved' and self.reserved_until > timezone.now()

    def __str__(self):
        return f"{self.seat.seat_number} reserved by {self.user.username}"