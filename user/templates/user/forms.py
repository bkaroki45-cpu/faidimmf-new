from django import forms

class PaymentForm(forms.Form):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, label='Amount')
    phone_number = forms.CharField(max_length=15, label='Phone Number')