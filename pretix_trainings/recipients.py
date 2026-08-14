from pretix.base.models import Order, OrderPosition


def _affected_positions(subevent):
    """OrderPosition mit subevent=X, deren Order pending oder paid ist (Konzept
    4.4). OrderPosition.objects filtert stornierte Positionen bereits per
    Default-Manager heraus; stornierte/abgelehnte Bestellungen werden über den
    Order-Status ausgeschlossen."""
    return (
        OrderPosition.objects.filter(
            subevent=subevent,
            order__status__in=[Order.STATUS_PENDING, Order.STATUS_PAID],
        )
        .select_related("order")
        .order_by("order_id", "positionid")
    )


def get_recipients(subevent):
    """Liefert {email: (order, position_oder_None)} - dedupliziert pro
    Adresse. attendee_email hat Vorrang vor order.email (Konzept 4.4). Wird
    eine E-Mail sowohl über eine Position als auch über order.email erreicht,
    gewinnt die erste Fundstelle in Bestell-/Positionsreihenfolge."""
    recipients = {}
    for position in _affected_positions(subevent):
        email = position.attendee_email or position.order.email
        if not email:
            continue
        recipients.setdefault(
            email, (position.order, position if position.attendee_email else None)
        )
    return recipients


def get_affected_order_count(subevent):
    return _affected_positions(subevent).values("order").distinct().count()
