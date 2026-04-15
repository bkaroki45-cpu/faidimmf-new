from django import forms
from user.models import TransactionPIN

class DepositForm(forms.Form):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, label='Amount')
    phone_number = forms.CharField(max_length=15, label='Phone Number')

    def __str__(self):
        return f"Deposit {self.amount} from {self.phone_number}"

class WithdrawForm(forms.Form):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, label='Amount')
    phone_number = forms.CharField(max_length=15, label='Phone Number')

    def __str__(self):
        return f"Withdraw {self.amount} to {self.phone_number}"
    
class InvestForm(forms.Form):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, label='Amount')

    def __str__(self):
        return f"Withdraw {self.amount} to {self.phone_number}"
    
# finance/forms.py

class PINForm(forms.ModelForm):
    pin = forms.CharField(
        max_length=6, 
        widget=forms.PasswordInput,
        help_text="Enter a 4-6 digit transaction PIN"
    )

    class Meta:
        model = TransactionPIN
        fields = []  # Leave empty because 'pin' is not a model field

    def save(self, commit=True, user=None):
        """Override save to hash the PIN."""
        raw_pin = self.cleaned_data['pin']
        if self.instance.pk is None:
            # Create new object
            self.instance.user = user
        self.instance.set_pin(raw_pin)  # uses model's set_pin method
        if commit:
            self.instance.save()
        return self.instance