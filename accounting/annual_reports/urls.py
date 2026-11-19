from django.urls import path
from . import views

app_name = 'annual_reports'

urlpatterns = [
    path('', views.annual_account_list, name='list'),
    path('<int:year>/', views.annual_account_detail, name='detail'),
]
