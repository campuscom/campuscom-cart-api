from decouple import config
import datetime
import uuid
import pytz
import jwt


class JWTMixin(object):
    def create_access_token(self, profile):
        return jwt.encode(
            {'id': str(profile.id),
                'uuid': str(uuid.uuid4()),
                'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=int(config('ACCESS_TOKEN_EXPIRY')))},
            config('ACCESS_TOKEN_SECRET'),
            algorithm=config('JWT_ALGORITHM'))

    def create_refresh_token(self, profile):
        return jwt.encode({
            'id': str(profile.id),
            'uuid': str(uuid.uuid4()),
            'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=int(config('REFRESH_TOKEN_EXPIRY')))},
            config('REFRESH_TOKEN_SECRET'),
            algorithm=config('JWT_ALGORITHM'))

    def create_user_token(self, profile):
        tokens_dict = {
            'access_token': self.create_access_token(profile),
            'refresh_token': self.create_refresh_token(profile),
            'expires_in': int(config('ACCESS_TOKEN_EXPIRY'))
        }

        return tokens_dict

    def set_cookies(self, response, tokens_dict):
        response.set_cookie(key='access_token', value=tokens_dict.get('access_token'), httponly=True, samesite='Strict', domain=config('FRONTEND_TLD'))
        response.set_cookie(key='refresh_token', value=tokens_dict.get('refresh_token'), httponly=True, samesite='Strict', domain=config('FRONTEND_TLD'))
        response.set_cookie(key='expires_in', value=str(tokens_dict.get('expires_in')), httponly=True, samesite='Strict', domain=config('FRONTEND_TLD'))


class ResponseFormaterMixin(object):
    def format_data(self, data, many=False):
        resp = {
            'url': config('API_URL', '') + self.request.get_full_path(),
            'date_time': datetime.datetime.now().replace(tzinfo=pytz.utc),
            'success': True,
        }

        if many:
            resp['total'] = len(data)

        resp['data'] = data
        return resp

    def object_decorator(self, obj):
        return self.format_data(obj)

    def list_decorator(self, obj_list):
        return self.format_data(obj_list, many=True)
