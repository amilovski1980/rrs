from django import forms
from django import template

register = template.Library()


@register.filter
def is_checkbox(field):
    return isinstance(getattr(field, "field", None) and field.field.widget, forms.CheckboxInput)
