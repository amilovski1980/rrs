from django import template

register = template.Library()


@register.filter
def matrix_on(matrix, key):
    if not isinstance(matrix, dict):
        return False
    return bool(matrix.get(key))
