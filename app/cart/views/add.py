from campuslibs.cart.common import create_cart
from django_scopes import scopes_disabled
from django.db.models import Sum

from rest_framework.views import APIView
from rest_framework.response import Response

from shared_models.models import Product, StoreCourseSection, StoreCertificate, Store, MembershipProgram, Profile

from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from cart.auth import IsAuthenticated
from cart.mixins import ResponseFormaterMixin, JWTMixin
from cart.utils import format_response, get_product_ids
from django.utils import timezone
from urllib.parse import parse_qs


class AddToCart(APIView, JWTMixin, ResponseFormaterMixin):
    http_method_names = ['head', 'get', 'post']
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        # how this endpoint works:
        # the old way was that the client would send a list of product ids. we find the corresponding entity (store course section, membership program, books or vegetables for that matter) from that list of product ids. we do that to exclude any product id that does not have a correspoding entity (yes, a particular product id may not have a corresponding entity) and to apply different eligibility rules (e.g. is the section marked enrollment_ready or is the membership program is available during the current date etc).

        # but now that the client will send in entity identification information (section external_id, course external_id etc) directly, instead of first converting them to product ids and then converting them to corresponding entities, we can directly use the corresponding entity ids.

        # but that will break backward compatibility. so, we will have to do one thing twice. here's what the flow will look like now:
        # 1. get the entity ids and convert them to entities (store_course_section, membership_program etc)
        # 2. get the products from those entities
        # 3. convert them again to entities to check availability etc
        # 4. the rest
        #
        # this is is suppose not the best way to do it.

        product_ids = request.data.get('product_ids', None)
        store_slug = request.data.get('store_slug', '')
        search_params = request.data.get('search_params', None)

        try:
            store = Store.objects.get(url_slug=store_slug)
        except Store.DoesNotExist:
            return Response({'message': 'No store found with that slug'}, status=HTTP_200_OK)
        # product_type = request.data.get('type', None)
        # course_external_id = request.data.get('course_external_id', None)
        # code = request.data.get('code', None)

        tid_isvalid = True
        if not product_ids:
            product_ids, tid_isvalid = get_product_ids(store, search_params)

        if not tid_isvalid:
            return Response({'message': 'token is expired'}, status=HTTP_200_OK)

        products = Product.objects.filter(id__in=product_ids, active_status=True)

        # get the products first
        with scopes_disabled():
            section_products = StoreCourseSection.objects.filter(
                store_course__enrollment_ready=True,
                product__in=products
            ).values('product')

            cert_products = StoreCertificate.objects.filter(
                enrollment_ready=True,
                product__in=products
            ).values('product')

            membership_program_products = MembershipProgram.objects.filter(
                product__id__in=products,
                store=store
            ).values('product')

            if membership_program_products:
                membership_programs = MembershipProgram.objects.filter(product__id__in=products, store=store)
                for membership_program in membership_programs:
                    if membership_program.membership_type == 'date_based':
                        if membership_program.start_date > timezone.now() or membership_program.end_date < timezone.now():
                            return Response({"message": "Membership Program Product is not valid"},
                                            status=HTTP_400_BAD_REQUEST)

        products = Product.objects.filter(
            id__in=section_products.union(cert_products, membership_program_products)
        )

        if not products.exists():
            return Response({'message': 'No product available'}, status=HTTP_200_OK)

        fee_aggregate = products.aggregate(total_amount=Sum('fee'))
        total_amount = fee_aggregate['total_amount']

        product_count = {}
        for product in products:
            product_id = str(product.id)
            if product_id in product_count:
                product_count[product_id] = product_count[product_id] + 1
            else:
                product_count[product_id] = 1

        cart = create_cart(store, products, product_count, total_amount, request.profile)

        data = format_response(store, products, cart)

        return Response(self.object_decorator(data), status=HTTP_200_OK)
