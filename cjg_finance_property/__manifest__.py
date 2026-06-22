# -*- coding: utf-8 -*-
# Copyright 2025 CJG

{
    "name": "Property Management",
    "description": """
        - Property Sale
        - Property Rental
        - Landlord Management
        - Customer Management
        - Property Maintenance
        - Customer Recurring Invoice
        - Property List
    """,
    "summary": """
        Property Sale
    """,
    "version": "17.0.1.2",
    "author": "Craulyn Feliz,Jeffry J. De La Rosa, Gregory Burgos",
    "category": "General",
    "company": "Infinity Services SRL",
    "maintainer": "TechKhedut Inc.",
    "website": "https://infinityservices.com.do",
    "depends": [
        "mail",
        "contacts",
        "account",
        "hr",
        "maintenance",
        "sale",
        "crm",
        "cjg_finance",
        "website",
        "base",
        "web",
        "stock_account",
        "purchase",
    ],
    "data": [
        # security
        "security/groups.xml",
        "security/ir.model.access.csv",
        "security/security.xml",
        # Data
        "data/ir_cron.xml",
        "data/sequence.xml",
        "data/contract_series_jm.xml",
        "data/property_product_data.xml",
        "data/payment_plan_template_data.xml",
        "data/cemetery_data.xml",
        # wizard views
        "wizard/property_payment_wizard_view.xml",
        "wizard/property_vendor_wizard_view.xml",
        "wizard/property_maintenance_wizard_view.xml",
        "wizard/booking_wizard_view.xml",
        "wizard/booking_inquiry_view.xml",
        "wizard/subproject_creation_view.xml",
        "wizard/unit_creation_view.xml",
        "wizard/exchange_rate_wizard_view.xml",
        "wizard/cambiar_parcela_wizard.xml",
        # Views
        "views/assets.xml",
        "views/property_details_view.xml",
        "views/property_document_view.xml",
        "views/user_type_view.xml",
        "views/property_amenities_view.xml",
        "views/property_specification_view.xml",
        "views/property_vendor_view.xml",
        "views/certificate_type_view.xml",
        "views/parent_property_view.xml",
        "views/property_tag_view.xml",
        "views/product_product_inherit_view.xml",
        "views/product_template_inherit_view.xml",
        "views/property_invoice_inherit.xml",
        "views/res_config_setting_view.xml",
        "views/property_res_city.xml",
        "views/configuration_views.xml",
        "views/property_region_views.xml",
        "views/property_project_view.xml",
        "views/property_sub_project_views.xml",
        "views/templates/property_web_template.xml",
        # Report views (must be loaded before buttons referencing actions)
        "report/maintenance_account_statement_report.xml",

        # Inherit Views
        "views/maintenance_product_inherit.xml",
        "views/property_maintenance_view.xml",
        "views/maintenance_request_report_button.xml",
        "views/property_crm_lead_inherit_view.xml",
        "views/sale_credit_view_fix.xml",
        "views/sale_order_view.xml",
        "views/sale_credit_property_products_view.xml",
        # Payment Plan Views
        "views/property_payment_plan_view.xml",
        "views/property_payment_plan_inherit_view.xml",
        "views/property_payment_plan_actions.xml",
        "views/property_details_actions.xml",
        # Cementerio (modelo fiel a Testarossa: jardín, parcela con cabida, reserva)
        "views/cemetery_views.xml",
        # Other Report views
        "report/property_details_report_v2.xml",
        "report/property_sold_report.xml",
        "report/property_payment_plan_report.xml",
        "report/property_brochure_enhanced_report.xml",
        "report/property_sales_offer_report.xml",
        "report/property_sales_offer_report_smart.xml",
        # Mail Template
        "data/property_book_mail_template.xml",
        "data/property_sold_mail_template.xml",
        # menus
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cjg_finance_property/static/src/css/style.css",
            "cjg_finance_property/static/src/css/lib/image-uploader.min.css",
            "cjg_finance_property/static/src/js/lib/image-uploader.min.js",
            "cjg_finance_property/static/src/xml/template.xml",
            "cjg_finance_property/static/src/scss/style.scss",
            "cjg_finance_property/static/src/js/lib/index.js",
            "cjg_finance_property/static/src/js/lib/map.js",
            "cjg_finance_property/static/src/js/lib/xy.js",
            "cjg_finance_property/static/src/js/lib/worldLow.js",
            "cjg_finance_property/static/src/js/lib/Animated.js",
            "cjg_finance_property/static/src/js/lib/apexcharts.js",
            "cjg_finance_property/static/src/js/property.js",
            'cjg_finance_property/static/src/components/**/*',
            'cjg_finance_property/static/src/views/**/*',
        ],
        "web.assets_frontend": [
            "cjg_finance_property/static/src/css/extra.css",
            "cjg_finance_property/static/src/js/portal_counter_patch.js",
        ],
    },
    "images": [
        "static/description/property-rental.gif",
    ],
    "license": "OPL-1",
    "installable": True,
    "application": True,
    "auto_install": False
}
