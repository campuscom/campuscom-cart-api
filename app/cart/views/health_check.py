from django.http import HttpResponse
from rest_framework.status import (
    HTTP_200_OK,
)


def health_check(request):
    return HttpResponse(status=HTTP_200_OK)
