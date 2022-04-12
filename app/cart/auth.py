from shared_models.models import Profile, StudentProfile, Store
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from decouple import config
import jwt
from rest_framework.exceptions import AuthenticationFailed
from urllib.parse import parse_qs


class IsAuthenticated(IsAuthenticated):

    def has_permission(self, request, view):
        search_params = request.data.get('search_params', None)
        checkout = request.query_params.get('checkout', 'nada')
        store_slug = request.data.get('store_slug', '')

        request.profile = None
        if checkout == 'guest':
            return True  # if checkout is guest, then no auth is required. profile will be none. cart will accept this gracefully.

        if 'access_token' in request.COOKIES:
            # if the user is actually logged in
            access_token = request.COOKIES['access_token']
            try:
                data = jwt.decode(str(access_token), config('ACCESS_TOKEN_SECRET'), algorithms=config('JWT_ALGORITHM'))
            except jwt.ExpiredSignatureError:
                raise AuthenticationFailed()
            except Exception as e:
                print(e)
                raise AuthenticationFailed()

            try:
                request.profile = Profile.objects.get(id=data['id'])
            except Profile.DoesNotExist:
                raise AuthenticationFailed()
            return True

        parsed_params = parse_qs(search_params)

        if 'pid' in parsed_params:
            try:
                profile_id = parsed_params.get('pid', [])[0]
            except IndexError:
                raise AuthenticationFailed()

            try:
                request.profile = Profile.objects.get(id=profile_id)
            except Profile.DoesNotExist:
                raise AuthenticationFailed()
            return True

        if 'primary_email' in parsed_params:
            try:
                store = Store.objects.get(url_slug=store_slug)
            except Store.DoesNotExist:
                return False

            profile, created = Profile.objects.update_or_create(
                primary_email=parsed_params.get('primary_email', [])[0],
                first_name=parsed_params.get('first_name', [])[0],
                last_name=parsed_params.get('last_name', [])[0]
            )
            student_profile, created = StudentProfile.objects.update_or_create(
                profile=profile,
                store=store,
                external_profile_id=parsed_params.get('student_id', [])[0]
            )
            return True

        # tid = when partner logged in user hit partner "checkout-info" with user and products data,
        # then we store the data in mongoDB and return them a token of encrypted mongo ObjectId
        # the hit checkout url with the token next time
        if 'tid' in parsed_params:
            request.profile = None

            return True

        raise AuthenticationFailed()

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.id == request.profile
