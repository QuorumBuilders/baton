from django import template

from accounts.phone_numbers import local_phone_number

register = template.Library()
register.filter("local_phone", local_phone_number)
