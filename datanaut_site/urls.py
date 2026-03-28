from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from landing import views as landing_views

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
]

urlpatterns += i18n_patterns(
    path("admin/", admin.site.urls),

    # ----- PORTAL LOGIN / LOGOUT -----
    path(
        "portal/login/",
        auth_views.LoginView.as_view(template_name="portal/login.html"),
        name="portal_login",
    ),
    path(
        "portal/logout/",
        auth_views.LogoutView.as_view(),
        name="portal_logout",
    ),

    # ----- Portal app -----
    path("portal/", include(("portal.urls", "portal"), namespace="portal")),

    # ----- Allauth -----
    path("accounts/", include("allauth.urls")),

    # ----- Marketing site -----
    path("", landing_views.home, name="home"),
    path("demo/", landing_views.demo, name="demo"),
    path("pricing/", landing_views.pricing, name="pricing"),
    path("contact/", landing_views.contact, name="contact"),
    path("about/", landing_views.about, name="about"),
    path("how-it-works/", landing_views.how_it_works, name="how_it_works"),
    path("who/trading-desks/", landing_views.for_trading_desks, name="for_trading_desks"),
    path("who/cfo-finance/", landing_views.for_cfo, name="for_cfo"),
    path("who/investors-board/", landing_views.for_investors, name="for_investors"),
    path("roi-calculator/", landing_views.roi_calculator, name="roi_calculator"),
    path("roi-calculator/export-pdf/", landing_views.export_report_pdf, name="export_report_pdf"),
    path("roi-calculator/export-xlsx/", landing_views.export_report_xlsx, name="export_report_xlsx"),
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)