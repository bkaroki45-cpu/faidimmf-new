from django import forms

from core.models import Contact

class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact  # THIS MUST POINT TO YOUR MODEL
        fields = ['name', 'email', 'phone', 'message']

    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'placeholder': 'Your Name',
            'class': 'form-input'
        })
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'placeholder': 'Your Email',
            'class': 'form-input'
        })
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Your Phone (optional)',
            'class': 'form-input'
        })
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'Your Message',
            'class': 'form-textarea',
            'rows': 6
        })
    )

    def __str__(self):
        return f"{self.name} - {self.email} - {self.message}"