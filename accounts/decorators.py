"""
This module contains some decorators to help you protect your views from
non-authorized access
"""
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.decorators import user_passes_test
from .models import Role, User


def writer_required(function=None,
                    redirect_field_name=REDIRECT_FIELD_NAME,
                    login_url='accounts:login'):
    decorator = user_passes_test(lambda u: u.is_active and
                                           User.objects.filter(pk=u.pk,
                                                               roles__pk=Role.WRITER)
                                 .exists(),
                                 login_url=login_url,
                                 redirect_field_name=redirect_field_name)
    if function:
        return decorator(function)
    return decorator


def user_creator(function=None,
                 redirect_field_name=REDIRECT_FIELD_NAME,
                 login_url='accounts:login'):
    decorator = user_passes_test(lambda u: u.is_active and
                                           (User.objects.filter(pk=u.pk, roles__pk=Role.ADMIN) or User.objects.filter(
                                               pk=u.pk, roles__pk=Role.WRITER))
                                 .exists(),
                                 login_url=login_url,
                                 redirect_field_name=redirect_field_name)
    if function:
        return decorator(function)
    return decorator


def admin_required(function=None,
                   redirect_field_name=REDIRECT_FIELD_NAME,
                   login_url='accounts:login'):
    decorator = user_passes_test(lambda u: u.is_active and \
                                           User.objects.filter(pk=u.pk,
                                                               roles__pk=Role.ADMIN)
                                 .exists(),
                                 login_url=login_url,
                                 redirect_field_name=redirect_field_name)
    if function:
        return decorator(function)
    return decorator


def approver_required(function=None,
                      redirect_field_name=REDIRECT_FIELD_NAME,
                      login_url='accounts:login'):
    decorator = user_passes_test(lambda u: u.is_active and \
                                           User.objects.filter(pk=u.pk,
                                                               roles__pk=Role.APPROVER)
                                 .exists(),
                                 login_url=login_url,
                                 redirect_field_name=redirect_field_name)
    if function:
        return decorator(function)
    return decorator


def user_admin_creator_required(function=None,
                                redirect_field_name=REDIRECT_FIELD_NAME,
                                login_url='accounts:login'):
    decorator = user_passes_test(lambda u: u.is_active and \
                                           User.objects.filter(pk=u.pk,
                                                               roles__pk=Role.ADMIN) or User.objects.filter(pk=u.pk,
                                                                                                            roles__pk=Role.APPROVER)
                                 .exists(),
                                 login_url=login_url,
                                 redirect_field_name=redirect_field_name)
    if function:
        return decorator(function)
    return decorator
