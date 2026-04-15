from django.urls import path
from . import views
 
app_name = 'user'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
    path('forgot_pin/', views.forgot_pin_request, name='forgot_pin_request'),
    path('forgot_pin/verify', views.forgot_pin_verify, name='forgot_pin_verify'),
    path('set_new_pin/', views.set_new_pin, name='set_new_pin'),
    path("forgot-password/", views.forgot_password, name="forgot_password"),
    path("verify-otp/", views.verify_otp, name="verify_otp"),
    path("reset-password/", views.reset_password, name="reset_password"),
]