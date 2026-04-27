from django.urls import path
from . import views
urlpatterns = [
    path('', views.movie_list, name='movie_list'),

    path('<int:movie_id>/theaters/', views.theater_list, name='theater_list'),
    path('<int:movie_id>/details/', views.details, name='details'),

    # Seat selection page (IMPORTANT - UI only)
    path('showtime/<int:showtime_id>/seats/', views.seat_selection, name='seat_selection'),

    # Razorpay flow
    path('showtime/<int:showtime_id>/create-order/', views.create_order, name='create_order'),
    path('verify-payment/', views.verify_payment, name='verify_payment'),

    # Optional fallback / backup
    path('payment/success/', views.payment_success, name='payment_success'),
    path('webhook/razorpay/', views.razorpay_webhook, name='razorpay_webhook'),

    # Seat unlock
    path('release-seats/', views.release_seats, name='release_seats'),

    # Admin
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
]