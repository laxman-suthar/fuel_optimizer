from django.urls import path
from .views import TripPlanView

urlpatterns = [
    path('trip/', TripPlanView.as_view(), name='trip-plan'),
]
