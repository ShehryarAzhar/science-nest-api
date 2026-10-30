from django.conf import settings
from django.urls import path
from django.views.generic import TemplateView

frontend_url = (
    f"{settings.DJOSER['EMAIL_FRONTEND_PROTOCOL']}://"
    f"{settings.DJOSER['EMAIL_FRONTEND_DOMAIN']}"
)

urlpatterns = [
    path(
        "",
        TemplateView.as_view(
            template_name="core/index.html",
            extra_context={"frontend_url": frontend_url},
        ),
        name="home",
    ),
]
