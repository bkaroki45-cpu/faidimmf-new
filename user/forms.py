from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, TransactionPIN  # import your custom user class directly
from django.contrib.auth import get_user_model



User = get_user_model()

class CustomUserCreationForm(UserCreationForm):
    referral_code = forms.CharField(required=False)

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'referral_code', 'password1', 'password2']



class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email']  # allow username/email change

# user/forms.py



# user/forms.py


# --- Set or Change PIN Form ---
class SetTransactionPINForm(forms.Form):
    pin = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Enter PIN'}),
        max_length=6, min_length=4,
        label="New PIN"
    )
    confirm_pin = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm PIN'}),
        max_length=6, min_length=4,
        label="Confirm PIN"
    )

    def clean(self):
        cleaned_data = super().clean()
        pin = cleaned_data.get("pin")
        confirm_pin = cleaned_data.get("confirm_pin")
        if not pin or not confirm_pin:
            raise forms.ValidationError("Both PIN fields are required.")
        if pin != confirm_pin:
            raise forms.ValidationError("PIN and Confirm PIN do not match.")
        return cleaned_data


# --- Change PIN Form (requires current PIN) ---
class ChangePINForm(forms.Form):
    current_pin = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Current PIN'}),
        max_length=6, min_length=4
    )
    new_pin = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'New PIN'}),
        max_length=6, min_length=4
    )
    confirm_new_pin = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm New PIN'}),
        max_length=6, min_length=4
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("new_pin") != cleaned_data.get("confirm_new_pin"):
            raise forms.ValidationError("New PIN and Confirm PIN do not match.")
        return cleaned_data


# --- Forgot PIN OTP Forms ---
# forms.py
from django import forms

class ForgotPINForm(forms.Form):
    email = forms.EmailField(label="Email", max_length=254)

class VerifyOTPForm(forms.Form):
    otp = forms.CharField(max_length=6, label="Enter OTP")
    









class SetNewPINForm(forms.Form):
    pin = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Enter new PIN'}),
        max_length=6,
        min_length=4,
        label="New PIN"
    )
    confirm_pin = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm new PIN'}),
        max_length=6,
        min_length=4,
        label="Confirm PIN"
    )

    def clean(self):
        cleaned_data = super().clean()
        pin = cleaned_data.get("pin")
        confirm_pin = cleaned_data.get("confirm_pin")
        if not pin or not confirm_pin:
            raise forms.ValidationError("Both PIN fields are required.")
        if pin != confirm_pin:
            raise forms.ValidationError("PIN and Confirm PIN do not match.")
        return cleaned_data