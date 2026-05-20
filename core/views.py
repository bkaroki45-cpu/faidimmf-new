from django.shortcuts import render, redirect
from django.conf import settings
from django.http import FileResponse, HttpResponse
from .forms import ContactForm
from .models import Contact

# Create your views here.

def home(request):
    return render(request, 'core/home.html')

def about(request):
    return render(request, 'core/about.html')

from django.shortcuts import render, redirect
from .forms import ContactForm

def contacts(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            # Do something, e.g., send email or save to DB
            name = form.cleaned_data['name']
            email = form.cleaned_data['email']
            phone = form.cleaned_data.get('phone', '')
            message = form.cleaned_data['message']
            print(name, email, phone, message) 
            form.save()
            return redirect('thank')  
    else:
        form = ContactForm()
    return render(request, 'core/contacts.html', {'form': form})

def invest(request):
    return render(request, 'core/invest.html')

def thank(request):
    return render(request, 'core/thank.html')


def favicon(request):
    icon_path = settings.BASE_DIR / 'static' / 'images' / 'favicon-48.png'
    return FileResponse(open(icon_path, 'rb'), content_type='image/png')


def robots_txt(request):
    base_url = f"{request.scheme}://{request.get_host()}"
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {base_url}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    base_url = f"{request.scheme}://{request.get_host()}"
    paths = ["", "about/", "contacts/"]
    urls = "\n".join(
        f"""  <url>
    <loc>{base_url}/{path}</loc>
    <changefreq>weekly</changefreq>
    <priority>{'1.0' if path == '' else '0.8'}</priority>
  </url>"""
        for path in paths
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>
"""
    return HttpResponse(xml, content_type="application/xml")


def indexnow_key(request):
    return HttpResponse(settings.INDEXNOW_KEY, content_type="text/plain")
