from django.urls import path, include

urlpatterns = [
    path('', include('django_components.middlewares.dependencies')),
]
