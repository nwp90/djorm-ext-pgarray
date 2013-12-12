# -*- coding: utf-8 -*-

import json

from django import forms
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import six
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _


TYPES = {
    'int': int,
    'smallint': int,
    'bigint': int,
    'text': str,
    'double precision': float,
    'varchar': str,
}


def _cast_to_unicode(data):
    if isinstance(data, (list, tuple)):
        return [_cast_to_unicode(x) for x in data]
    elif isinstance(data, str):
        return force_text(data)
    return data


def _cast_to_type(data, type_cast):
    if isinstance(data, (list, tuple)):
        return [_cast_to_type(x, type_cast) for x in data]
    if type_cast == str:
        return force_text(data)
    return type_cast(data)


def _unserialize(value):
    try:
        return json.loads(value)
    except ValueError:
        # Not sure when this was expected to happen.
        # Presumably a string, but not a valid JSON string.
        # Also not sure what benefit it of doing this.
        return _cast_to_unicode(value)


class ArrayField(models.Field):
    __metaclass__ = models.SubfieldBase

    def __init__(self, *args, **kwargs):
        self._array_type = kwargs.pop('dbtype', 'int')
        type_key = self._array_type.split('(')[0]

        if "type_cast" in kwargs:
            self._type_cast = kwargs.pop("type_cast")
        elif type_key in TYPES:
            self._type_cast = TYPES[type_key]
        else:
            self._type_cast = lambda x: x

        self._valid = set(kwargs.pop('valid', []))
        self._dimension = kwargs.pop('dimension', 1)
        kwargs.setdefault('blank', True)
        kwargs.setdefault('null', True)
        kwargs.setdefault('default', None)
        super(ArrayField, self).__init__(*args, **kwargs)

    def formfield(self, **params):
        params.setdefault('form_class', ArrayFormField)
        params.setdefault('type_cast', self._type_cast)
        return super(ArrayField, self).formfield(**params)

    def db_type(self, connection):
        return '{0}{1}'.format(self._array_type, "[]" * self._dimension)

    # Perform db-specific conversion; value returned should be ready for
    # use as a parameter to a query.
    def get_db_prep_value(self, value, connection, prepared=False):
        return value

    # Perform db-agnostic conversion; prepare value for use in a query.
    def get_prep_value(self, value):
        return value

    # Called to convert a value from db or serialized data to
    # python representation
    def to_python(self, value):
        if value is None:
            return value
        if isinstance(value, six.string_types):
            value = _unserialize(value)
        return _cast_to_type(value, self._type_cast)

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return json.dumps(self.get_prep_value(value),
                          cls=DjangoJSONEncoder)

    def validate(self, value, model_instance):
        if not self.editable:
            # Skip validation for non-editable fields.
            return
        for val in value:
            if self._valid and not (val in self._valid):
                msg = self.error_messages['invalid_choice'] % val
                msg = "val %s not in valid %s" % (repr(val), self._valid)
                raise ValidationError(msg)
  
            super(ArrayField, self).validate(val, model_instance)


# South support
try:
    from south.modelsinspector import add_introspection_rules
    add_introspection_rules([
        (
            [ArrayField], # class
            [],           # positional params
            {
                "dbtype": ["_array_type", {"default": "int"}],
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ['^djorm_pgarray\.fields\.ArrayField'])
except ImportError:
    pass


class ArrayFormField(forms.Field):
    default_error_messages = {
        'invalid': _('Enter a list of values, joined by commas.  E.g. "a,b,c".'),
    }

    def __init__(
            self, max_length=None, min_length=None, delim=None, type_cast=None,
            *args, **kwargs):
        if delim is not None:
            self.delim = delim
        else:
            self.delim = ','
        if type_cast is None:
            self._type_cast = lambda x: x
        else:
            self._type_cast = type_cast
        super(ArrayFormField, self).__init__(*args, **kwargs)

    def clean(self, value):
        if not value:
            return []
#        return self.to_python(value)
        try:
            return self.to_python(value)
        except Exception:
            raise ValidationError(self.error_messages['invalid'])

    def prepare_value(self, value):
        if isinstance(value, (list, tuple, set)):
            if value:
                return self.delim.join(str(v) for v in value)
        return super(ArrayFormField, self).prepare_value(value)

    def to_python(self, value):
        if not isinstance(value, (list, tuple, set)):
            value = value.split(self.delim)
        return _cast_to_type(value, self._type_cast)
