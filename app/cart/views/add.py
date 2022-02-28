from campuslibs.cart.common import validate_coupon, create_cart, apply_discounts, tax_apply
from django_scopes import scopes_disabled
from django.db.models import Sum

from decimal import Decimal

from rest_framework.views import APIView
from rest_framework.response import Response

from shared_models.models import Product, StoreCourseSection, StoreCertificate, StorePaymentGateway, ProfileQuestion, \
    RegistrationQuestion, StoreCompany, RelatedProduct, PaymentQuestion, Store, MembershipProgram

from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST

from cart.auth import IsAuthenticated
from cart.mixins import ResponseFormaterMixin
from cart.serializers import StoreSerializer
from decouple import config
from django.utils import timezone


class AddToCart(APIView, ResponseFormaterMixin):
    http_method_names = ['head', 'get', 'post']
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        product_ids = request.data.get('product_ids', None)
        coupon_code = request.data.get('coupon_code', None)
        zip_code = request.data.get('zip_code', None)

        store_slug = request.data.get('store_slug', '')

        try:
            store = Store.objects.get(url_slug=store_slug)
        except Store.DoesNotExist:
            return Response({'message': 'No store found with that slug'}, status=HTTP_200_OK)

        # get the products first
        with scopes_disabled():
            section_products = StoreCourseSection.objects.filter(
                store_course__enrollment_ready=True,
                product__in=product_ids
            ).values('product')

            cert_products = StoreCertificate.objects.filter(
                enrollment_ready=True,
                product__in=product_ids
            ).values('product')

            membership_program_products = MembershipProgram.objects.filter(
                product__id__in=product_ids,
                store=store
            ).values('product')

            if membership_program_products:
                membership_programs = MembershipProgram.objects.filter(product__id__in=product_ids, store=store)
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
        for product_id in product_ids:
            if product_id in product_count:
                product_count[product_id] = product_count[product_id] + 1
            else:
                product_count[str(product_id)] = 1

        cart = create_cart(store, products, product_count, total_amount, request.profile)  # cart must belong to a profile or guest

        discount_amount = Decimal('0.0')
        coupon, coupon_message = validate_coupon(store, coupon_code, request.profile)
        if coupon:
            discount_amount = apply_discounts(coupon.discount_program)

        sales_tax, tax_message = tax_apply(zip_code, products, cart)

        data = format_response(store, products, cart, discount_amount, coupon_message, sales_tax, tax_message)

        return Response(self.object_decorator(data), status=HTTP_200_OK)


def format_response(store, products, cart, discount_amount, coupon_message, sales_tax, tax_message):
    store_serializer = StoreSerializer(store)

    payment_gateways = []
    for item in StorePaymentGateway.objects.filter(store=store):
        payment_gateways.append({
            'id': str(item.id),
            'name': item.payment_gateway.name,
            'branding': item.branding
        })

    all_items = []
    profile_question_course_provider = ProfileQuestion.objects.none()
    profile_question_store = ProfileQuestion.objects.none()
    registration_questions = RegistrationQuestion.objects.none()

    for product in products:
        product_data = {}

        with scopes_disabled():
            store = product.store
            course_provider = None

            # getting registration questions
            if product.product_type == 'section':
                course_provider = product.store_course_section.store_course.course.course_provider

                registration_questions = RegistrationQuestion.objects.filter(
                    entity_type='course',
                    entity_id=product.store_course_section.store_course.course.id
                )

            elif product.product_type == 'certificate':
                course_provider = product.store_certificate.certificate.course_provider
                registration_questions = RegistrationQuestion.objects.filter(
                    entity_type='certificate',
                    entity_id=product.store_certificate.certificate.id
                )

            # getting profile questions
            if course_provider:
                profile_question_course_provider = profile_question_course_provider.union(
                    ProfileQuestion.objects.filter(
                        provider_type='course_provider', provider_ref=course_provider.id
                    )
                )
            profile_question_store = profile_question_store.union(
                ProfileQuestion.objects.filter(provider_type='store',
                    provider_ref=store.id
                )
            )

            registration_question_list = []
            for question in registration_questions:
                question_details = {
                    "id": question.question_bank.id,
                    "type": question.question_bank.question_type,
                    "label": question.question_bank.title,
                    "display_order": question.display_order,
                    "configuration": question.question_bank.configuration
                }
                registration_question_list.append(question_details)

            if product.product_type == 'membership':
                product_image_uri = ''
                if product.image:
                    product_image_uri = config('CDN_URL') + 'uploads' + product.image.url
                product_data = {
                    'id': str(product.id),
                    'title': product.title,
                    'slug': '',
                    'image_uri': product_image_uri,
                    'external_image_url': '',
                    'provider': {'id': '', 'code': ''},
                    'price': product.fee,
                    'product_type': 'membership',
                    'section': {
                        'start_date': '',
                        'end_date': '',
                        'execution_site': '',
                        'execution_mode': '',
                        'name': '',
                        'product_id': '',
                        'price': '',
                        'instructor': '',
                    },
                    'sections': [],
                    'registration_questions': [],
                    'related_products': [],
                }
            else:
                try:
                    store_certificate = StoreCertificate.objects.get(product=product)
                except StoreCertificate.DoesNotExist:
                    pass
                else:
                    if store_certificate.certificate.certificate_image_uri:
                        image_uri = config('CDN_URL') + 'uploads' + store_certificate.certificate.certificate_image_uri.url
                    else:
                        image_uri = store_certificate.certificate.external_image_url

                    product_data = {
                        'id': str(store_certificate.certificate.id),
                        'title': store_certificate.certificate.title,
                        'slug': store_certificate.certificate.slug,
                        'image_uri': image_uri,
                        'external_image_url': store_certificate.certificate.external_image_url,
                        'provider': {
                            'id': store_certificate.certificate.course_provider.content_db_reference,
                            'code': store_certificate.certificate.course_provider.code
                        },
                        'price': product.fee,
                        'product_type': 'certificate'
                    }

                try:
                    store_course_section = StoreCourseSection.objects.get(product=product)
                except StoreCourseSection.DoesNotExist:
                    pass
                else:
                    if store_course_section.store_course.course.course_image_uri:
                        image_uri = config('CDN_URL') + 'uploads' + store_course_section.store_course.course.course_image_uri.url
                    else:
                        image_uri = store_course_section.store_course.course.external_image_url

                    section_data = []
                    for scc in StoreCourseSection.objects.filter(store_course=store_course_section.store_course,
                                                                store_course__enrollment_ready=True):
                        section_data.append({
                            'start_date': scc.section.start_date,
                            'end_date': scc.section.end_date,
                            'execution_site': scc.section.execution_site,
                            'execution_mode': scc.section.execution_mode,
                            'name': scc.section.name,
                            'product_id': scc.product.id,
                            'price': scc.section.fee,
                            'instructor': "",  # will come from mongodb
                        })

                    related_products = RelatedProduct.objects.filter(product=product.id)
                    related_product_list = []

                    for related_product in related_products:
                        related_product_image_uri = None
                        if related_product.related_product.image:
                            related_product_image_uri = config('CDN_URL') + 'uploads' + related_product.related_product.image.url

                        details = {
                            'id': str(related_product.related_product.id),
                            'title': related_product.related_product.title,
                            'image_uri': related_product_image_uri,
                            'product_type': related_product.related_product.product_type,
                            'relation_type': related_product.related_product_type,
                            'price': related_product.related_product.fee
                        }
                        related_product_list.append(details)

                    # membership_programs = MembershipProgram.objects.filter(store=store)
                    # membership_program_product_list = []

                    # for program in membership_programs:
                    #     product_image_uri = None
                    #     if program.product.image:
                    #         product_image_uri = config('CDN_URL') + 'uploads' + program.product.image.url

                    #     details = {
                    #         'id': str(program.product.id),
                    #         'title': program.product.title,
                    #         'image_uri': product_image_uri,
                    #         'product_type': program.product.product_type,
                    #         'price': program.product.fee
                    #     }
                    #     membership_program_product_list.append(details)


                    product_data = {
                        'id': str(product.id),
                        'title': store_course_section.store_course.course.title,
                        'slug': store_course_section.store_course.course.slug,
                        'image_uri': image_uri,
                        'external_image_url': store_course_section.store_course.course.external_image_url,
                        'provider': {
                            'id': store_course_section.store_course.course.course_provider.content_db_reference,
                            'code': store_course_section.store_course.course.course_provider.code
                        },
                        'product_type': 'store_course_section',
                        'section': {
                            'start_date': store_course_section.section.start_date,
                            'end_date': store_course_section.section.end_date,
                            'execution_site': store_course_section.section.execution_site,
                            'execution_mode': store_course_section.section.execution_mode,
                            'name': store_course_section.section.name,
                            'product_id': product.id,
                            'price': product.fee,
                            'instructor': "",  # will come from mongodb
                        },
                        'sections': section_data,
                        'price': product.fee,

                        'registration_questions': registration_question_list,
                        'related_products': related_product_list,
                        # 'membership_products': membership_program_product_list
                    }
        all_items.append(product_data)

    profile_question_list = []
    course_provider_max_order = 1
    for question in profile_question_course_provider:
        if course_provider_max_order < question.display_order:
            course_provider_max_order = question.display_order

        unique_questions = {}
        for ql in profile_question_list:
            unique_questions[ql["id"]] = ql

        if question.question_bank.id in list({questions["id"]: questions for questions in profile_question_list}):
            if question.respondent_type != unique_questions[question.question_bank.id]["respondent_type"]:
                question_details = {
                    "id": question.question_bank.id,
                    "type": question.question_bank.question_type,
                    "label": question.question_bank.title,
                    "display_order": question.display_order,
                    "configuration": question.question_bank.configuration,
                    "respondent_type": question.respondent_type
                }
                profile_question_list.append(question_details)
        else:
            question_details = {
                "id": question.question_bank.id,
                "type": question.question_bank.question_type,
                "label": question.question_bank.title,
                "display_order": question.display_order,
                "configuration": question.question_bank.configuration,
                "respondent_type": question.respondent_type
            }
            profile_question_list.append(question_details)

    for question in profile_question_store:
        unique_questions = {}
        for ql in profile_question_list:
            unique_questions[ql["id"]] = ql

        if question.question_bank.id in list({questions["id"]: questions for questions in profile_question_list}):
            if question.respondent_type != unique_questions[question.question_bank.id]["respondent_type"]:
                question_details = {
                    "id": question.question_bank.id,
                    "type": question.question_bank.question_type,
                    "label": question.question_bank.title,
                    "display_order": question.display_order + course_provider_max_order,
                    "configuration": question.question_bank.configuration,
                    "respondent_type": question.respondent_type
                }
                profile_question_list.append(question_details)
        else:
            question_details = {
                "id": question.question_bank.id,
                "type": question.question_bank.question_type,
                "label": question.question_bank.title,
                "display_order": question.display_order + course_provider_max_order,
                "configuration": question.question_bank.configuration,
                "respondent_type": question.respondent_type
            }
            profile_question_list.append(question_details)

    companies = StoreCompany.objects.filter(store=store.id)
    company_list = []
    for company in companies:
        company_details = {
            "id": company.id,
            "name": company.company_name
        }
        company_list.append(company_details)

    payment_question_list = []
    payment_questions = PaymentQuestion.objects.filter(store=store.id)
    for question in payment_questions:
        question_details = {
            "id": question.question_bank.id,
            "type": question.question_bank.question_type,
            "label": question.question_bank.title,
            "display_order": question.display_order,
            "configuration": question.question_bank.configuration
        }
        payment_question_list.append(question_details)

    data = {
        'discount_amount': discount_amount,
        'coupon_message': coupon_message,
        'sales_tax': sales_tax,
        'tax_message': tax_message,
        'products': all_items,
        'payment_gateways': payment_gateways,
        'cart_id': str(cart.id) if cart is not None else '',
        'store': store_serializer.data,
        'profile_questions': profile_question_list,
        'companies': company_list,
        'payment_questions': payment_question_list
    }
    return data
