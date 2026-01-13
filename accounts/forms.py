from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, PasswordChangeForm
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.forms import TextInput, Select

from accounts.models import Role, User


class BaseForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super(BaseForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'


class UserForm(UserCreationForm):
    """
    This is the user creation form. You can add or exclude any fields you
    might want or not want. You can tweak it to your liking, see the django
    documentation if needed...
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('first_name', 'last_name', 'email', 'telephone', 'username')
        exclude = []

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        if User.objects.filter(pk=user.pk, roles__id=Role.ADMIN):
            print("oui oui")
        else:
            self.fields['roles'].queryset = Role.objects.filter(id__in=[1, 2])


class UserChangePass(PasswordChangeForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = '__all__'
        exclude = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['old_password'].widget = TextInput(attrs={
            'class': 'form-control',
            'type': 'password'})
        self.fields['new_password1'].widget = TextInput(attrs={
            'class': 'form-control',
            'type': 'password'})
        self.fields['new_password2'].widget = TextInput(attrs={
            'class': 'form-control',
            'type': 'password'})


class UpdateForm(UserChangeForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'telephone', 'username')
        exclude = []

    def __init__(self, *args, **kwargs):
        # user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        # if User.objects.filter(pk=user.pk, roles__id=Role.ADMIN):
        #   pass
        # else:
        #   self.fields['center'].queryset = Antenne.objects.filter(id=user.center.id)
        #  self.fields['roles'].queryset = Role.objects.filter(id__in=[1,2])

