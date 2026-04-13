from datetime import datetime, timezone

from kindr_app.models import Campaign, Donation

CATEGORY_LABELS = {
    "education": "Education",
    "health": "Health & Medical",
    "environment": "Environment",
    "community": "Community",
    "arts": "Arts & Culture",
    "animals": "Animals",
    "emergency": "Emergency",
}

DEFAULT_CAMPAIGN_IMAGE = (
    "https://images.unsplash.com/photo-1559027615-cd4628902d4a?w=600&q=80"
)


def normalize_category_slug(raw: str) -> str:
    s = (raw or "").strip().lower()
    rules = [
        ("education", ("education", "school", "university", "stem", "scholar", "learn")),
        ("health", ("health", "medical", "clinic", "hospital", "care")),
        ("environment", ("environment", "climate", "tree", "forest", "green")),
        ("community", ("community", "local", "village", "town")),
        ("arts", ("arts", "culture", "music", "creative", "theatre")),
        ("animals", ("animal", "wildlife", "pet", "shelter")),
        ("emergency", ("emergency", "relief", "disaster", "flood", "fire")),
    ]
    for slug, keys in rules:
        if any(k in s for k in keys):
            return slug
    return "community"


def category_label(slug: str) -> str:
    return CATEGORY_LABELS.get(slug, slug.replace("-", " ").title())


def campaign_to_public_dict(c: Campaign) -> dict:
    recent_rows = (
        Donation.query.filter_by(campaign_id=c.id, status="success")
        .order_by(Donation.created_at.desc())
        .limit(3)
        .all()
    )
    now = datetime.now(timezone.utc)
    recent_payments = []
    for d in recent_rows:
        name = (d.payer_name or "").strip() or "Anonymous donor"
        created = d.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        mins_ago = None
        if created is not None:
            mins_ago = max(0, int((now - created).total_seconds() // 60))
        if mins_ago is None:
            ago_text = "recently"
        elif mins_ago < 60:
            ago_text = f"{mins_ago} min ago"
        elif mins_ago < 1440:
            ago_text = f"{mins_ago // 60} hr ago"
        else:
            ago_text = f"{mins_ago // 1440} day ago"
        recent_payments.append(
            {
                "name": name,
                "amount": float(d.amount or 0),
                "ago": ago_text,
            }
        )

    slug = normalize_category_slug(c.category or "community")
    return {
        "id": c.id,
        "title": c.title,
        "category": slug,
        "category_label": category_label(slug),
        "image": c.image_url or DEFAULT_CAMPAIGN_IMAGE,
        "description": c.description,
        "raised": float(c.raised_amount or 0),
        "target": float(c.goal_amount),
        "donor_count": int(c.donor_count or 0),
        "recent_payments": recent_payments,
    }


def user_payload(u) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "phone": u.phone,
        "is_admin": bool(getattr(u, "is_admin", False)),
    }
