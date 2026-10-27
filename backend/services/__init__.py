# Services package — avoid importing valuation PDF (WeasyPrint) at package import time;
# use ``import services.report_service`` or ``from services import report_service`` at call sites.
from .analytics_service import get_singapore_summary as get_singapore_summary, get_district_analytics as get_district_analytics
from .geospatial_service import get_nearby_mrts as get_nearby_mrts, get_insights_for_area as get_insights_for_area
from .sentiment_service import get_market_sentiment as get_market_sentiment
