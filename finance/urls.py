from django.urls import path
from finance.query import query_status
from finance.stkpush import stk_push
from . import views

app_name = 'finance'

urlpatterns = [
    path('deposit/', views.deposit, name='deposit'),
    path('withdraw/', views.withdraw, name='withdraw'),
    path('transactions/', views.transactions, name='transactions'),
    path('invest/tracking/', views.invest_tracking, name='invest_tracking'),
    path('invest/', views.invest, name='invest'),
    path('referrals/', views.referrals, name='referrals'),
    path('accesstoken/', views.get_access_token_value, name='get_access_token'),
    path('stkpush/', stk_push, name='stk_push'),
    path('query/', query_status, name='query_status'),
    path('callback/', views.mpesa_callback, name='mpesa_callback'),
    path('set-pin/', views.set_pin, name='set_pin'),
]