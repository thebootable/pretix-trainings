"""Anonymisierung personenbezogener Daten für einzelne, bereits vergangene
Kurstermine (Subevents) - siehe NOTES.md für die Abgrenzung zu pretix'
eigenem, event-weiten Datenschutz-Bereich (`pretix.base.shredder`), dessen
Voraussetzung ("alle Subevents des Events sind vorbei") für Schulungsreihen
mit laufend neuen Terminen praktisch nie erfüllt ist.

Anonymisiert wird statt gelöscht (die Bestellung bleibt für Buchhaltung/
Statistik bestehen), in Anlehnung an die Feld- und Kategorienauswahl von
pretix' eigenen Shreddern. Für Kategorien, die sich auf die ganze Bestellung
statt eine einzelne Position beziehen (Kontaktdaten, Rechnungsadresse,
Rechnungen, Zahlungsdaten, kombinierte Tickets), wird nur angefasst, wessen
Bestellung *ausschließlich* Positionen in bereits vergangenen Terminen hat -
sonst würde eine Bestellung, die zusätzlich einen noch bevorstehenden Termin
enthält, ihre noch benötigten Kontakt-/Zahlungsdaten verlieren."""

from collections import defaultdict
from django.db import transaction
from django.db.models import Q
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from pretix.base.models import (
    CachedCombinedTicket,
    CachedTicket,
    Invoice,
    InvoiceAddress,
    OrderPayment,
    OrderPosition,
    OrderRefund,
    QuestionAnswer,
)

CATEGORY_ATTENDEE_DATA = "attendee_data"
CATEGORY_QUESTIONS = "questions"
CATEGORY_TICKETS = "tickets"
CATEGORY_CONTACT_DATA = "contact_data"
CATEGORY_INVOICE_ADDRESS = "invoice_address"
CATEGORY_INVOICES = "invoices"
CATEGORY_PAYMENT_DATA = "payment_data"


def subevent_is_over(subevent):
    if subevent is None:
        return False
    end = subevent.date_to or subevent.date_from
    return end is not None and end < now()


def _order_ids_for_subevent(se):
    return set(
        OrderPosition.all.filter(order__event=se.event, subevent=se)
        .values_list("order_id", flat=True)
        .distinct()
    )


def _order_ids_fully_over(order_ids):
    """Teilmenge von order_ids, bei der ALLE Positionen der Bestellung zu
    bereits vergangenen Terminen gehören."""
    if not order_ids:
        return set()
    positions_by_order = defaultdict(list)
    for pos in OrderPosition.all.filter(order_id__in=order_ids).select_related(
        "subevent"
    ):
        positions_by_order[pos.order_id].append(pos)
    return {
        order_id
        for order_id, positions in positions_by_order.items()
        if all(subevent_is_over(p.subevent) for p in positions)
    }


def _attendee_data_qs(se):
    return OrderPosition.all.filter(subevent=se).filter(
        Q(attendee_name_cached__isnull=False)
        | Q(attendee_name_parts__isnull=False)
        | ~Q(company="")
        | ~Q(street="")
        | ~Q(zipcode="")
        | ~Q(city="")
    )


def _apply_attendee_data(se, order_ids, fully_over_ids):
    n = _attendee_data_qs(se).update(
        attendee_name_cached=None,
        attendee_name_parts={"_shredded": True},
        company="",
        street="",
        zipcode="",
        city="",
    )
    OrderPosition.all.filter(subevent=se, attendee_email__isnull=False).update(
        attendee_email=None
    )
    return n


def _questions_qs(se):
    return QuestionAnswer.objects.filter(orderposition__subevent=se)


def _apply_questions(se, order_ids, fully_over_ids):
    qs = _questions_qs(se)
    n = qs.count()
    for answer in qs:
        if answer.file:
            answer.file.delete(save=False)
    qs.delete()
    return n


def _tickets_qs(se):
    return CachedTicket.objects.filter(order_position__subevent=se)


def _apply_tickets(se, order_ids, fully_over_ids):
    n = _tickets_qs(se).count()
    _tickets_qs(se).delete()
    n += CachedCombinedTicket.objects.filter(order_id__in=fully_over_ids).count()
    CachedCombinedTicket.objects.filter(order_id__in=fully_over_ids).delete()
    return n


def _contact_data_qs(order_ids, fully_over_ids):
    from pretix.base.models import Order

    return Order.objects.filter(pk__in=fully_over_ids).filter(
        Q(email__isnull=False) | Q(phone__isnull=False) | Q(customer__isnull=False)
    )


def _apply_contact_data(se, order_ids, fully_over_ids):
    n = _contact_data_qs(order_ids, fully_over_ids).count()
    _contact_data_qs(order_ids, fully_over_ids).update(
        email=None, phone="", customer=None
    )
    return n


def _invoice_address_qs(order_ids, fully_over_ids):
    return InvoiceAddress.objects.filter(order_id__in=fully_over_ids)


def _apply_invoice_address(se, order_ids, fully_over_ids):
    qs = _invoice_address_qs(order_ids, fully_over_ids)
    n = qs.count()
    qs.delete()
    return n


def _invoices_qs(order_ids, fully_over_ids):
    return Invoice.objects.filter(order_id__in=fully_over_ids, shredded=False)


def _apply_invoices(se, order_ids, fully_over_ids):
    qs = _invoices_qs(order_ids, fully_over_ids)
    n = 0
    for invoice in qs:
        if invoice.file:
            invoice.file.delete(save=False)
        invoice.shredded = True
        invoice.introductory_text = "█"
        invoice.additional_text = "█"
        invoice.invoice_to = "█"
        invoice.payment_provider_text = "█"
        invoice.transmission_info = {"_shredded": True}
        invoice.save()
        invoice.lines.update(description="█")
        n += 1
    return n


def _payment_data_qs(order_ids, fully_over_ids):
    return OrderPayment.objects.filter(order_id__in=fully_over_ids)


def _apply_payment_data(se, order_ids, fully_over_ids):
    event = se.event
    provs = event.get_payment_providers()
    payments = list(_payment_data_qs(order_ids, fully_over_ids))
    refunds = list(OrderRefund.objects.filter(order_id__in=fully_over_ids))
    n = 0
    for obj in payments + refunds:
        pprov = provs.get(obj.provider)
        if pprov:
            pprov.shred_payment_info(obj)
            n += 1
    return n


CATEGORIES = [
    {
        "id": CATEGORY_ATTENDEE_DATA,
        "label": _("Teilnehmerdaten"),
        "description": _(
            "Namen und Anschriften auf den Buchungspositionen dieses Termins."
        ),
        "tax_relevant": False,
        "count": lambda se, oi, fo: _attendee_data_qs(se).count(),
        "apply": _apply_attendee_data,
    },
    {
        "id": CATEGORY_QUESTIONS,
        "label": _("Fragen-Antworten"),
        "description": _(
            "Antworten auf Bestellfragen zu Buchungspositionen dieses Termins."
        ),
        "tax_relevant": False,
        "count": lambda se, oi, fo: _questions_qs(se).count(),
        "apply": _apply_questions,
    },
    {
        "id": CATEGORY_TICKETS,
        "label": _("Tickets"),
        "description": _(
            "Zwischengespeicherte Ticket-PDFs. Werden bei Bedarf neu erzeugt."
        ),
        "tax_relevant": False,
        "count": lambda se, oi, fo: _tickets_qs(se).count(),
        "apply": _apply_tickets,
    },
    {
        "id": CATEGORY_CONTACT_DATA,
        "label": _("Kontaktdaten"),
        "description": _(
            "E-Mail-Adresse, Telefonnummer und Kundenkonto-Verknüpfung der "
            "Bestellung - nur bei Bestellungen, die ausschließlich Positionen "
            "in bereits vergangenen Terminen enthalten."
        ),
        "tax_relevant": False,
        "count": lambda se, oi, fo: _contact_data_qs(oi, fo).count(),
        "apply": _apply_contact_data,
    },
    {
        "id": CATEGORY_INVOICE_ADDRESS,
        "label": _("Rechnungsadresse"),
        "description": _(
            "Rechnungsadresse der Bestellung - nur bei Bestellungen, die "
            "ausschließlich Positionen in bereits vergangenen Terminen "
            "enthalten."
        ),
        "tax_relevant": True,
        "count": lambda se, oi, fo: _invoice_address_qs(oi, fo).count(),
        "apply": _apply_invoice_address,
    },
    {
        "id": CATEGORY_INVOICES,
        "label": _("Rechnungen"),
        "description": _(
            "Rechnungs-PDFs und deren personenbezogener Textinhalt. "
            "Rechnungsnummer und Beträge bleiben erhalten - nur bei "
            "Bestellungen, die ausschließlich Positionen in bereits "
            "vergangenen Terminen enthalten."
        ),
        "tax_relevant": True,
        "count": lambda se, oi, fo: _invoices_qs(oi, fo).count(),
        "apply": _apply_invoices,
    },
    {
        "id": CATEGORY_PAYMENT_DATA,
        "label": _("Zahlungsdaten"),
        "description": _(
            "Zahlungs- und Rückerstattungsdaten, soweit der jeweilige "
            "Zahlungsdienstleister eine Löschung unterstützt - nur bei "
            "Bestellungen, die ausschließlich Positionen in bereits "
            "vergangenen Terminen enthalten."
        ),
        "tax_relevant": True,
        "count": lambda se, oi, fo: (
            _payment_data_qs(oi, fo).count()
            + OrderRefund.objects.filter(order_id__in=fo).count()
        ),
        "apply": _apply_payment_data,
    },
]

CATEGORIES_BY_ID = {c["id"]: c for c in CATEGORIES}


def get_counts(se):
    """Betroffene-Datensätze-Zahl je Kategorie, für die Bestätigungsseite."""
    order_ids = _order_ids_for_subevent(se)
    fully_over_ids = _order_ids_fully_over(order_ids)
    return (
        {c["id"]: c["count"](se, order_ids, fully_over_ids) for c in CATEGORIES},
        len(order_ids),
        len(fully_over_ids),
    )


def anonymize_subevent(se, category_ids, user):
    """Führt die Anonymisierung für die ausgewählten Kategorien aus und
    protokolliert das Ergebnis als LogEntry am Subevent."""
    order_ids = _order_ids_for_subevent(se)
    fully_over_ids = _order_ids_fully_over(order_ids)

    results = {}
    with transaction.atomic():
        for category_id in category_ids:
            category = CATEGORIES_BY_ID[category_id]
            results[category_id] = category["apply"](se, order_ids, fully_over_ids)

        se.log_action(
            action="pretix_trainings.subevent.anonymized",
            user=user,
            data={"categories": category_ids, "counts": results},
        )
    return results
