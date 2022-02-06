from campuslibs.cart.common import coupon_apply

from rest_framework.views import APIView
from rest_framework.response import Response

from shared_models.models import Product, Store, Profile, MembershipProgramParticipant, MembershipProgramCoupon, Cart
from rest_framework.status import HTTP_200_OK

from cart.auth import IsAuthenticated
from cart.mixins import ResponseFormaterMixin
from decimal import Decimal

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


def get_membership_coupons(profile, store):
    if profile:
        try:
            member = MembershipProgramParticipant.objects.get(profile=profile, membership_program__store=store)
        except MembershipProgramParticipant.DoesNotExist:
            pass
        else:
            membership_coupons = MembershipProgramCoupon.objects.filter(membership_program=member.membership_program)
            return member, [mcoupon.coupon for mcoupon in membership_coupons]
    return None, []

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

        coupon_code = request.data.get('coupon_code', None)

        cart_items = format_payload(cart_details)

        sub_total = Decimal('0.00')
        total_discount = Decimal('0.00')
        total_payable = sub_total - total_discount

        discounts = []
        products = []
        coupon_messages = []

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
                    'title': related_product.title,
                    'quantity': int(related_item['quantity']),
                    'product_type': related_product.product_type,
                    'item_price': related_product.fee,
                    'price': related_product.fee * int(related_item['quantity']),
                })
                sub_total = sub_total + (related_product.fee * int(related_item['quantity']))

            products.append({
                'title': product.title,
                'quantity': int(item['quantity']),
                'product_type': product.product_type,
                'item_price': product.fee,
                'price': product.fee * int(item['quantity']),
                'related_products': related_products
            })
            sub_total = sub_total + (product.fee * int(item['quantity']))

        # sub_total updated. so update total_payable too
        total_payable = sub_total - total_discount

        # membership section
        # get the memberships this particular user bought
        member, membership_coupons = get_membership_coupons(profile, store)
        if member:
            membership_discount = Decimal('0.00')
            for mcoupon in membership_coupons:
                coupon, discount_amount, coupon_message = coupon_apply(store, mcoupon.code, total_payable, profile, cart)

                if coupon is not None:
                    total_discount = total_discount + discount_amount
                    membership_discount = membership_discount + discount_amount

                    discounts.append({
                        'type': 'membership',
                        'title': member.membership_program.title,
                        'amount': membership_discount
                    })
        # total_discount updated. so update total_payable too
        total_payable = sub_total - total_discount

        # coupon section

        if coupon_code in [mcoupon.code for mcoupon in membership_coupons]:
            coupon_messages.append({
                'code': coupon_code,
                'message': 'This coupon is already applied as a membership privilege'
            })
        else:
            if coupon_code:
                coupon, discount_amount, coupon_message = coupon_apply(store, coupon_code, sub_total, profile, cart)

                if coupon is not None:
                    discounts.append({
                        'type': 'coupon',
                        'code': coupon.code,
                        'amount': discount_amount
                    })

                    total_discount = total_discount + discount_amount
                    # total_discount updated. so update total_payable too
                    total_payable = sub_total - total_discount
                else:
                    coupon_messages.append({
                        'code': coupon_code,
                        'message': coupon_message
                    })



        data = {
            'products': products,
            'discounts': discounts,
            'subtotal': sub_total,
            'total_discount': total_discount,
            'total_payable': total_payable,
            'coupon_messages': coupon_messages
        }

        return Response(self.object_decorator(data), status=HTTP_200_OK)
