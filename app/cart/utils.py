from django_scopes import scopes_disabled

from shared_models.models import StoreCourseSection, StoreCertificate, StorePaymentGateway, ProfileQuestion, \
    RegistrationQuestion, StoreCompany, RelatedProduct, PaymentQuestion, Course

from cart.serializers import StoreSerializer
from decouple import config

from models.course.course import Course as CourseModel
from models.courseprovider.course_provider import CourseProvider as CourseProviderModel
from models.checkout.checkout_login_user import CheckoutLoginUser as CheckoutLoginUserModel
from shared_models.models import Course, StoreCourseSection, CourseSharingContract
from django_scopes import scopes_disabled
from urllib.parse import parse_qs


def format_response(store, products, cart):
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
                    'external_id': str(product.external_id),
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
                        image_uri = config(
                            'CDN_URL') + 'uploads' + store_certificate.certificate.certificate_image_uri.url
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
                        image_uri = config(
                            'CDN_URL') + 'uploads' + store_course_section.store_course.course.course_image_uri.url
                    else:
                        image_uri = store_course_section.store_course.course.external_image_url

                    course_model = []
                    try:
                        course_model = CourseModel.objects.get(id=store_course_section.section.content_db_reference)
                    except CourseModel.DoesNotExist:
                        continue

                    section_data = []
                    for scc in StoreCourseSection.objects.filter(store_course=store_course_section.store_course,
                                                                 store_course__enrollment_ready=True):
                        for section_model in course_model.sections:
                            if section_model.code == scc.section.name:
                                external_id = section_model.external_id
                        section_data.append({
                            'start_date': scc.section.start_date,
                            'end_date': scc.section.end_date,
                            'execution_site': scc.section.execution_site,
                            'execution_mode': scc.section.execution_mode,
                            'name': scc.section.name,
                            'external_id': external_id,
                            'product_id': scc.product.id,
                            'price': scc.section.fee,
                            'instructor': "",  # will come from mongodb
                        })

                    related_products = RelatedProduct.objects.filter(product=product.id)
                    related_product_list = []

                    for related_product in related_products:
                        related_product_image_uri = None
                        if related_product.related_product.image:
                            related_product_image_uri = config(
                                'CDN_URL') + 'uploads' + related_product.related_product.image.url

                        details = {
                            'id': str(related_product.related_product.id),
                            'external_id': str(related_product.related_product.external_id),
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

                    for section_model in course_model.sections:
                        if section_model.code == store_course_section.section.name:
                            external_id = section_model.external_id

                    product_data = {
                        'id': str(product.id),
                        'external_id': str(product.external_id),
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
                            'external_id': external_id,
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
        'products': all_items,
        'payment_gateways': payment_gateways,
        'cart_id': str(cart.id) if cart is not None else '',
        'store': store_serializer.data,
        'profile_questions': profile_question_list,
        'companies': company_list,
        'payment_questions': payment_question_list
    }
    return data


def get_product_ids(store, search_params):
    parsed_params = parse_qs(search_params)

    provider_codes = [item[0] for item in CourseSharingContract.objects.filter(store=store).values_list('course_provider__code')]

    product_ids = []
    external_ids = []

    if 'section' in parsed_params:
        external_ids = parsed_params.get('section', [])

    # tid = when partner logged in user hit partner "checkout-info" with user and products data,
    # then we store the data in mongoDB and return them a token of encrypted mongo ObjectId
    # the hit checkout url with the token next time
    elif 'tid' in parsed_params:
        token = parsed_params.get('tid', None)

        try:
            mongo_data = CheckoutLoginUserModel.objects.get(token=token[0])
        except CheckoutLoginUserModel.DoesNotExist:
            pass
        else:
            try:
                products = mongo_data['payload']['students'][0]['products']

                for product in products:
                    if product['product_type'] == 'section':
                        if external_ids:
                            external_ids[0] = external_ids[0]+','+product['id']
                        else:
                            external_ids.append(product['id'])
            except KeyError:
                pass

    for item in external_ids:
        for section in item.split(','):
            course_external_id, section_external_id = section.split('__')

            course_provider_models = CourseProviderModel.objects.filter(
                code__in=provider_codes
            )

            # as there are multiple course providers, the following query may return multiple courses. what should
            # happen should it does is not determined yet.
            try:
                course_model = CourseModel.objects.get(
                    provider__in=course_provider_models,
                    external_id=course_external_id
                )
            except CourseModel.DoesNotExist:
                continue
            except CourseModel.MultipleObjectsReturned:
                raise NotImplementedError

            with scopes_disabled():
                try:
                    # this query also may return multiple objects
                    course = Course.objects.get(
                        content_db_reference=str(course_model.id),
                        course_provider__code__in=provider_codes
                    )
                except Course.DoesNotExist:
                    continue
                except Course.MultipleObjectsReturned:
                    raise NotImplementedError

                # get the section name. section name and section code are same. but external_id is different.
                # so make one more loop and more db transaction to get the name. otherwise won't work.
                section_name = ''
                for section_model in course_model.sections:
                    if section_model.external_id == section_external_id:
                        section_name = section_model.code
                        break

                try:
                    store_course_section = StoreCourseSection.objects.get(
                        # since external_id in SectionModel is the same as code in SectionModel and that in turn is the same as name in Section
                        section__name=section_name,
                        store_course__course=course,
                        store_course__store=store,
                    )
                except StoreCourseSection.DoesNotExist:
                    continue
                else:
                    try:

                        store_course_section = StoreCourseSection.objects.get(
                            # since external_id in SectionModel is the same as code in SectionModel and that in turn is the same as name in Section
                            section__name=section_name,
                            store_course__course=course,
                            store_course__store=store
                        )
                    except StoreCourseSection.DoesNotExist:

                        product_ids.append(str(store_course_section.product.id))
                    except AttributeError:

                        continue

    return product_ids
