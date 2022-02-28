from rest_framework.views import APIView
from rest_framework.response import Response

from shared_models.models import Product, Store, Profile, Cart
from rest_framework.status import HTTP_200_OK

from cart.auth import IsAuthenticated
from cart.mixins import ResponseFormaterMixin
from decimal import Decimal

from campuslibs.cart.common import validate_membership, apply_per_product_discounts, validate_coupon

def format_payload(payload):
    # payload data format is designed insensibly.
    # here we reformat it in a more meaningful way.

    # first we separate related and non-related products
    products = [
        {
            'product_id': item['product_id'],
            'quantity': item['quantity'],
            'student_email': item['student_email'],
            'related_products': []
        } for item in payload if not item['is_related']
    ]

    related_products = [
        {
            'product_id': item['product_id'],
            'quantity': item['quantity'],
            'related_to': item['related_to'],
            'student_email': item['student_email']
        } for item in payload if item['is_related']
    ]

    for idx, product in enumerate(products):
        for related_product in related_products:
            if product['product_id'] == related_product['related_to']:
                products[idx]['related_products'].append({
                    'product_id': related_product['product_id'],
                    'quantity': related_product['quantity'],
                    'student_email': related_product['student_email']
                })
    return products


class PaymentSummary(APIView, ResponseFormaterMixin):
    http_method_names = ['head', 'get', 'post']
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        cart_id = request.data.get('cart_id', None)
        cart = None

        if cart_id:
            try:
                cart = Cart.objects.get(id=cart_id)
            except Cart.DoesNotExist:
                pass

        cart_details = request.data.get('cart_details', [])
        if not cart_details:
            return Response({'message': 'invalid cart details'}, status=HTTP_200_OK)

        purchaser = request.data.get('purchaser_info', {})

        profile = request.profile

        try:
            primary_email = purchaser['primary_email']
        except KeyError:
            pass
        else:
            try:
                profile = Profile.objects.get(primary_email=primary_email)
            except (Profile.DoesNotExist, Profile.MultipleObjectsReturned):
                pass

        try:
            store = Store.objects.get(url_slug=request.data.get('store_slug', None))
        except Store.DoesNotExist:
            return Response({'message': 'invalid store slug'}, status=HTTP_200_OK)

        coupon_codes = request.data.get('coupon_codes', [])

        cart_items = format_payload(cart_details)

        products = []
        sub_total = Decimal('0.0')

        for item in cart_items:
            try:
                product = Product.objects.get(id=item['product_id'])
            except Product.DoesNotExist:
                continue

            related_products = []

            for related_item in item['related_products']:
                try:
                    related_product = Product.objects.get(id=related_item['product_id'])
                except Product.DoesNotExist:
                    continue

                related_products.append({
                    'id': str(related_product.id),
                    'title': related_product.title,
                    'quantity': int(related_item['quantity']),
                    'product_type': related_product.product_type,
                    'item_price': related_product.fee,
                    'price': related_product.fee * int(related_item['quantity']),
                    'discounts': [],
                    'total_discount': Decimal('0.0'),
                    'minimum_fee': related_product.minimum_fee,
                    'gross_amount': related_product.fee * int(related_item['quantity']),
                    'total_amount': related_product.fee * int(related_item['quantity']),
                })
                sub_total = sub_total + (related_product.fee * int(related_item['quantity']))

            products.append({
                'id': str(product.id),
                'title': product.title,
                'quantity': int(item['quantity']),
                'product_type': product.product_type,
                'item_price': product.fee,
                'price': product.fee * int(item['quantity']),
                'related_products': related_products,
                'discounts': [],
                'total_discount': Decimal('0.0'),
                'minimum_fee': product.minimum_fee,
                'gross_amount': product.fee * int(item['quantity']),
                'total_amount': product.fee * int(item['quantity']),
            })
            sub_total = sub_total + (product.fee * int(item['quantity']))

        # membership section
        # get the memberships this particular user bought

        membership_program = validate_membership(store, profile)
        if membership_program:
            for mpd in membership_program.membershipprogramdiscount_set.all():
                products = apply_per_product_discounts(mpd.discount_program, products=products)

        # coupon section

        # TODO: first, check if discount_program from membership and discount_program from coupon are both the same.
        # if not, only then proceed. same discount_program can only be applied once.
        for coupon_code in coupon_codes:
            discount_program, coupon_message = validate_coupon(store, coupon_code, profile)
            if discount_program:
                products = apply_per_product_discounts(discount_program, products=products)

        total_discount = Decimal('0.0')

        for p_idx, product in enumerate(products):
            if 'discounts' in product:
                for d_idx, discount in enumerate(products[p_idx]['discounts']):
                    products[p_idx]['discounts'][d_idx].pop('rule', None)
                    products[p_idx]['discounts'][d_idx].pop('program', None)


            if 'related_products' in product:
                for related_idx, related_product in enumerate(products[p_idx]['related_products']):
                    if 'discounts' in related_product:
                        for d_idx, discount in enumerate(products[p_idx]['related_products'][related_idx]['discounts']):
                            products[p_idx]['related_products'][related_idx]['discounts'][d_idx].pop('rule', None)
                            products[p_idx]['related_products'][related_idx]['discounts'][d_idx].pop('program', None)

                    try:
                        total_discount = total_discount + related_product['total_discount']
                    except KeyError:
                        pass
            try:
                total_discount = total_discount + product['total_discount']
            except KeyError:
                pass

        data = {
            'products': products,
            'subtotal': sub_total,
            'total_discount': total_discount,
            'total_payable': sub_total - total_discount,
        }
        return Response(self.object_decorator(data), status=HTTP_200_OK)
