# cases/views_customer_portal.py
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError

from customers.models import CustomerMembership
from cases.models import Debtor

User = get_user_model()


def _cp_context(request):
    """
    Contexte Client Portal basé sur CustomerMembership (comme CustomerPortalMeView).
    Retourne: (membership, customer, tenant)
    """
    membership = (
        CustomerMembership.objects
        .select_related("customer", "user", "customer__tenant")
        .filter(user=request.user)
        .order_by("-id")
        .first()
    )
    if not membership:
        raise PermissionDenied("No active customer membership for this user.")

    customer = membership.customer
    if not customer:
        raise PermissionDenied("Customer not found for membership.")

    # optionnel: portal_enabled
    if hasattr(customer, "portal_enabled") and not customer.portal_enabled:
        raise PermissionDenied("Customer portal is not enabled.")

    # optionnel: membership status
    if hasattr(membership, "status") and membership.status in ("suspended", "disabled"):
        raise PermissionDenied("Account is suspended.")

    tenant = getattr(customer, "tenant", None)
    if not tenant:
        raise PermissionDenied("No tenant found for this customer.")

    return membership, customer, tenant


class CustomerPortalDebtorsView(APIView):
    """
    GET /customer-portal/debtors/?q=
    POST /customer-portal/debtors/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _, customer, tenant = _cp_context(request)

        qs = Debtor.objects.filter(
            tenant=tenant,
            created_via="customer_portal",
            source_customer=customer,
        )

        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(full_name__icontains=q)

        qs = qs.order_by("full_name")

        data = [
            {
                "id": d.id,
                "type": d.type,
                "full_name": d.full_name,
                "national_id": d.national_id,
                "tax_id": d.tax_id,
                "phone": d.phone,
                "email": d.email,
                "address": d.address,
                "city": d.city,
                "country": d.country,
                "metadata": d.metadata,
                "created_at": d.created_at,
            }
            for d in qs
        ]
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        _, customer, tenant = _cp_context(request)
        payload = request.data or {}

        full_name = (payload.get("full_name") or "").strip()
        if not full_name:
            raise ValidationError({"full_name": "This field is required."})

        debtor_type = payload.get("type") or "individual"
        if debtor_type not in ("individual", "company"):
            raise ValidationError({"type": "Invalid type."})

        d = Debtor.objects.create(
            tenant=tenant,
            type=debtor_type,
            full_name=full_name,
            national_id=(payload.get("national_id") or None),
            tax_id=(payload.get("tax_id") or None),
            phone=(payload.get("phone") or None),
            email=(payload.get("email") or None),
            address=(payload.get("address") or None),
            city=(payload.get("city") or None),
            country=(payload.get("country") or None),
            metadata=(payload.get("metadata") or None),
            created_via="customer_portal",
            source_customer=customer,
        )

        return Response(
            {
                "id": d.id,
                "type": d.type,
                "full_name": d.full_name,
                "national_id": d.national_id,
                "tax_id": d.tax_id,
                "phone": d.phone,
                "email": d.email,
                "address": d.address,
                "city": d.city,
                "country": d.country,
                "metadata": d.metadata,
                "created_at": d.created_at,
            },
            status=status.HTTP_201_CREATED,
        )


class CustomerPortalDebtorDetailView(APIView):
    """
    PATCH /customer-portal/debtors/<id>/
    DELETE /customer-portal/debtors/<id>/
    """
    permission_classes = [IsAuthenticated]

    def _get_object(self, request, debtor_id: int):
        _, customer, tenant = _cp_context(request)
        d = Debtor.objects.filter(
            id=debtor_id,
            tenant=tenant,
            created_via="customer_portal",
            source_customer=customer,
        ).first()
        if not d:
            raise NotFound("Debtor not found.")
        return d

    def patch(self, request, debtor_id: int):
        d = self._get_object(request, debtor_id)
        payload = request.data or {}

        # champs modifiables
        for f in ["type", "full_name", "national_id", "tax_id", "phone", "email", "address", "city", "country", "metadata"]:
            if f in payload:
                setattr(d, f, payload.get(f) or None)

        if not (d.full_name or "").strip():
            raise ValidationError({"full_name": "This field is required."})

        if d.type not in ("individual", "company"):
            raise ValidationError({"type": "Invalid type."})

        d.save()

        return Response(
            {
                "id": d.id,
                "type": d.type,
                "full_name": d.full_name,
                "national_id": d.national_id,
                "tax_id": d.tax_id,
                "phone": d.phone,
                "email": d.email,
                "address": d.address,
                "city": d.city,
                "country": d.country,
                "metadata": d.metadata,
                "created_at": d.created_at,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, debtor_id: int):
        d = self._get_object(request, debtor_id)
        d.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _generate_temp_password(length: int = 12) -> str:
    import secrets
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class CustomerPortalUsersView(APIView):
    """
    GET /customer-portal/users/         -> liste des users du customer courant
    POST /customer-portal/users/        -> crée un user + membership du customer courant
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _, customer, _ = _cp_context(request)
        qs = customer.memberships.select_related("user").all().order_by("-id")

        data = []
        for m in qs:
            u = m.user
            data.append({
                "id": u.id,
                "username": u.username,
                "first_name": getattr(u, "first_name", None),
                "last_name": getattr(u, "last_name", None),
                "email": getattr(u, "email", None),
                "role": getattr(m, "role", None),
                "status": getattr(m, "status", None),
                "is_primary_contact": getattr(m, "is_primary_contact", False),
            })

        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        actor_membership, customer, _ = _cp_context(request)

        # sécurité simple: seul owner/manager peut ajouter des users
        if getattr(actor_membership, "role", None) not in ("owner", "manager"):
            raise PermissionDenied("Not allowed.")

        payload = request.data or {}
        username = (payload.get("username") or "").strip()
        email = (payload.get("email") or "").strip() or None
        first_name = (payload.get("first_name") or "").strip() or ""
        last_name = (payload.get("last_name") or "").strip() or ""
        role = payload.get("role") or "viewer"

        if not username:
            raise ValidationError({"username": "This field is required."})

        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError({"username": "This username is already used."})

        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError({"email": "This email is already used."})

        temp_password = _generate_temp_password(12)

        with transaction.atomic():
            u = User.objects.create(
                username=username,
                email=email or "",
                first_name=first_name,
                last_name=last_name,
                is_active=True,
            )
            u.set_password(temp_password)
            u.must_change_password = True
            u.save(update_fields=["password", "must_change_password"])

            # membership client portal -> CustomerMembership existe déjà chez toi
            # on reste cohérent avec ton CustomerViewSet/memberships()
            m = CustomerMembership.objects.create(
                customer=customer,
                user=u,
                role=role,
                status="active",  # ou "invited" si tu veux un onboarding; ici on active direct
                is_primary_contact=False,
            )

        # si email, on envoie les identifiants
        if email:
            login_url = getattr(settings, "FRONTEND_CLIENT_PORTAL_LOGIN_URL", "") or ""
            subject = "ACX - Client Portal access"
            lines = [
                f"Hello {first_name or username},",
                "",
                f"You have been added to the Client Portal for: {customer.name}",
                "",
                f"Login URL: {login_url}" if login_url else "Login URL: (not configured)",
                f"Username: {username}",
                f"Temporary password: {temp_password}",
                "",
                "Please change your password after logging in.",
                "",
                "ACX",
            ]
            send_mail(
                subject=subject,
                message="\n".join(lines),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[email],
                fail_silently=False,
            )

        return Response(
            {
                "id": u.id,
                "username": u.username,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "email": u.email or None,
                "role": m.role,
                "status": m.status,
                "is_primary_contact": m.is_primary_contact,
                # utile si pas d'email
                "temporary_password": temp_password if not email else None,
            },
            status=status.HTTP_201_CREATED,
        )


class CustomerPortalUserUpdateView(APIView):
    """
    PATCH /customer-portal/users/<user_id>/
    -> update role/status/is_active pour un user du même customer
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, user_id: int):
        actor_membership, customer, _ = _cp_context(request)

        if getattr(actor_membership, "role", None) not in ("owner", "manager"):
            raise PermissionDenied("Not allowed.")

        m = customer.memberships.select_related("user").filter(user_id=user_id).first()
        if not m:
            raise NotFound("User not found for this customer.")

        payload = request.data or {}

        # membership updates
        if "role" in payload:
            m.role = payload.get("role") or m.role
        if "status" in payload:
            m.status = payload.get("status") or m.status
        if "is_primary_contact" in payload:
            m.is_primary_contact = bool(payload.get("is_primary_contact"))

        m.save()

        u = m.user
        # user updates optionnels
        if "is_active" in payload:
            u.is_active = bool(payload.get("is_active"))
            u.save(update_fields=["is_active"])

        return Response(
            {
                "id": u.id,
                "username": u.username,
                "first_name": getattr(u, "first_name", None),
                "last_name": getattr(u, "last_name", None),
                "email": getattr(u, "email", None),
                "role": m.role,
                "status": m.status,
                "is_primary_contact": m.is_primary_contact,
            },
            status=status.HTTP_200_OK,
        )


class CustomerPortalAssigneesView(APIView):
    """
    GET /customer-portal/assignees/
    -> liste des users actifs du customer courant (pour l'assignation des dossiers)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _, customer, _ = _cp_context(request)

        qs = customer.memberships.select_related("user").all().order_by("user__username")

        data = []
        for m in qs:
            u = m.user
            # on garde uniquement les users "actifs" côté membership + user
            if getattr(m, "status", None) != "active":
                continue
            if hasattr(u, "is_active") and not u.is_active:
                continue

            data.append({
                "id": u.id,
                "username": u.username,
                "first_name": getattr(u, "first_name", None),
                "last_name": getattr(u, "last_name", None),
                "email": getattr(u, "email", None),
                "role": getattr(m, "role", None),
                "status": getattr(m, "status", None),
            })

        return Response(data, status=status.HTTP_200_OK)


from rest_framework.parsers import MultiPartParser, FormParser
from cases.models import Case, CaseDocument


class CustomerPortalCaseDocumentsView(APIView):
    """
    GET  /customer-portal/cases/<case_id>/documents/  -> liste docs
    POST /customer-portal/cases/<case_id>/documents/  -> upload doc (multipart)
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _get_case(self, request, case_id: int):
        membership, customer, tenant = _cp_context(request)
        c = Case.objects.filter(id=case_id, tenant=tenant, customer=customer).first()
        if not c:
            raise NotFound("Case not found.")
        return c, customer

    def get(self, request, case_id: int):
        case, customer = self._get_case(request, case_id)

        qs = CaseDocument.objects.filter(case=case, customer=customer).order_by("-id")
        data = []
        for d in qs:
            data.append({
                "id": d.id,
                "title": d.title,
                "doc_type": d.doc_type,
                "file": d.file.url if d.file else None,
                "created_at": d.created_at,
                "uploaded_by": getattr(d.uploaded_by, "username", None) if d.uploaded_by else None,
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request, case_id: int):
        case, customer = self._get_case(request, case_id)

        title = (request.data.get("title") or "").strip()
        doc_type = request.data.get("doc_type") or "other"
        f = request.FILES.get("file")

        if not title:
            raise ValidationError({"title": "This field is required."})
        if not f:
            raise ValidationError({"file": "File is required."})

        d = CaseDocument.objects.create(
            customer=customer,
            case=case,
            uploaded_by=request.user,
            title=title,
            doc_type=doc_type,
            file=f,
        )

        return Response(
            {
                "id": d.id,
                "title": d.title,
                "doc_type": d.doc_type,
                "file": request.build_absolute_uri(d.file.url) if d.file else None,
                "created_at": d.created_at,
                "uploaded_by": getattr(d.uploaded_by, "username", None) if d.uploaded_by else None,
            },
            status=status.HTTP_201_CREATED,
        )



class CustomerPortalCaseDocumentDetailView(APIView):
    """
    PATCH  /customer-portal/cases/<case_id>/documents/<doc_id>/
      - multipart/form-data
      - fields optionnels: title, doc_type, file (remplacement)
    DELETE /customer-portal/cases/<case_id>/documents/<doc_id>/
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _get_case_and_doc(self, request, case_id: int, doc_id: int):
        # même logique que ton CustomerPortalCaseDocumentsView
        membership, customer, tenant = _cp_context(request)

        case = Case.objects.filter(id=case_id, tenant=tenant, customer=customer).first()
        if not case:
            raise NotFound("Case not found.")

        doc = CaseDocument.objects.filter(id=doc_id, case=case, customer=customer).first()
        if not doc:
            raise NotFound("Document not found.")

        return case, customer, doc

    def patch(self, request, case_id: int, doc_id: int):
        case, customer, doc = self._get_case_and_doc(request, case_id, doc_id)

        title = request.data.get("title")
        doc_type = request.data.get("doc_type")
        f = request.FILES.get("file")

        # au moins un champ doit être fourni
        if title is None and doc_type is None and f is None:
            raise ValidationError({"detail": "No fields provided."})

        if title is not None:
            title = (title or "").strip()
            if not title:
                raise ValidationError({"title": "This field is required."})
            doc.title = title

        if doc_type is not None:
            doc.doc_type = (doc_type or "other")

        if f is not None:
            # remplacement du fichier
            doc.file = f

        doc.save()

        return Response(
            {
                "id": doc.id,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "file": request.build_absolute_uri(doc.file.url) if doc.file else None,
                "created_at": doc.created_at,
                "uploaded_by": getattr(doc.uploaded_by, "username", None) if doc.uploaded_by else None,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, case_id: int, doc_id: int):
        case, customer, doc = self._get_case_and_doc(request, case_id, doc_id)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

from cases.models import Case, CaseNote

class CustomerPortalCaseNoteDetailView(APIView):
    """
    PATCH  /customer-portal/cases/<case_id>/notes/<note_id>/
    DELETE /customer-portal/cases/<case_id>/notes/<note_id>/
    """
    permission_classes = [IsAuthenticated]

    def _get_case(self, request, case_id: int):
        membership, customer, tenant = _cp_context(request)
        case = Case.objects.filter(id=case_id, tenant=tenant, customer=customer).first()
        if not case:
            raise NotFound("Case not found.")
        return membership, customer, tenant, case

    def _get_note(self, case: Case, note_id: int):
        note = CaseNote.objects.select_related("author").filter(id=note_id, case=case).first()
        if not note:
            raise NotFound("Note not found.")
        return note

    def _can_manage(self, membership, note: CaseNote, user):
        # ✅ règle: auteur peut modifier/supprimer
        if note.author_id == user.id:
            return True
        # ✅ owner/manager du customer peut gérer les notes
        role = getattr(membership, "role", None)
        return role in ("owner", "manager")

    def patch(self, request, case_id: int, note_id: int):
        membership, customer, tenant, case = self._get_case(request, case_id)
        note = self._get_note(case, note_id)

        if not self._can_manage(membership, note, request.user):
            raise PermissionDenied("Not allowed.")

        body = (request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "This field is required."})

        note.body = body
        note.save(update_fields=["body"])

        return Response(
            {
                "id": note.id,
                "body": note.body,
                "created_at": note.created_at.isoformat(),
                "author_username": note.author.username if note.author else None,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, case_id: int, note_id: int):
        membership, customer, tenant, case = self._get_case(request, case_id)
        note = self._get_note(case, note_id)

        if not self._can_manage(membership, note, request.user):
            raise PermissionDenied("Not allowed.")

        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)