from django.shortcuts import render, redirect
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