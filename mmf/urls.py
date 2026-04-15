from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView  # ✅ for redirect

# Optional: preserve query string in redirect
class RegisterRedirectWithQuery(RedirectView):
    url = '/user/register/'
    permanent = False
    query_string = True  # ✅ keep ?ref=XYZ

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),  # Core pages
    path('user/', include(('user.urls', 'user'), namespace='user')),
    path('finance/', include(('finance.urls', 'finance'), namespace='finance')),

    # Preserve referral code in redirect
    path('register/', RegisterRedirectWithQuery.as_view()),
]