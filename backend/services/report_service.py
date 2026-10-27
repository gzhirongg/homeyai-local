from io import BytesIO
from datetime import datetime
import base64
from pathlib import Path

from weasyprint import HTML, CSS

from services.report_assets import get_logo_base64


def get_default_report_config() -> dict:
    return {f"include_{name}": True for name in (
        "property_details", "valuation_summary", "amenities", "market_insights",
        "market_sentiment", "comparative_analysis",
    )}


def interval_description(valuation_data: dict) -> tuple[str, str]:
    if valuation_data.get("confidence_interval_method") == "split_conformal_relative":
        calibration = valuation_data.get("interval_calibration") or {}
        coverage = float(valuation_data.get("interval_coverage", .9)) * 100
        observed = calibration.get("test_coverage")
        text = f"Target coverage {coverage:.0f}%; calibrated on held-out sales."
        if observed is not None:
            text += f" Later temporal test coverage: {float(observed)*100:.1f}%."
        return f"{coverage:.0f}% target prediction interval", text + " Future coverage can change with the market."
    return "Estimated price range", "A fixed +/-10% heuristic, not a calibrated prediction interval."


def _valuation_preview_css() -> str:
    root = Path(__file__).resolve().parent.parent / "static" / "reports"
    base = (root / "base_report.css").read_text(encoding="utf-8")
    valuation_extra = (root / "valuation_report.css").read_text(encoding="utf-8")
    return f"{base}\n{valuation_extra}"

def _shap_rows_for_report(shap_values) -> list[dict]:
    """Normalize valuation ``shap_values`` to ``{feature, contribution}`` rows for HTML tables."""
    if not shap_values:
        return []
    if isinstance(shap_values, list):
        rows: list[dict] = []
        for item in shap_values:
            if not isinstance(item, dict):
                continue
            feature = item.get("feature")
            if not feature:
                continue
            contrib = item.get("contribution_sgd")
            if contrib is None:
                contrib = item.get("contribution")
            if contrib is None:
                contrib = item.get("contribution_log", 0)
            try:
                contrib_f = float(contrib)
            except (TypeError, ValueError):
                contrib_f = 0.0
            rows.append({"feature": str(feature), "contribution": contrib_f})
        return rows
    if isinstance(shap_values, dict):
        contribs = shap_values.get("contributions")
        if not isinstance(contribs, list):
            return []
        rows = []
        for item in contribs:
            if not isinstance(item, dict):
                continue
            feature = item.get("feature")
            if not feature:
                continue
            contrib = item.get("contribution_sgd")
            if contrib is None:
                contrib = item.get("contribution")
            if contrib is None:
                contrib = item.get("contribution_log", 0)
            try:
                contrib_f = float(contrib)
            except (TypeError, ValueError):
                contrib_f = 0.0
            rows.append({"feature": str(feature), "contribution": contrib_f})
        return rows
    return []


def generate_valuation_report(
    property_data: dict,
    valuation_data: dict,
    report_config: dict,
    user_email: str,
    market_sentiment: dict = None,
    comparative_data: dict = None
) -> BytesIO:
    """
    Generate a professional PDF valuation report using WeasyPrint for perfect HTML fidelity.
    """
    # 1. Generate the exact same HTML as the preview
    html_content, _ = generate_html_preview(
        property_data, 
        valuation_data, 
        report_config, 
        user_email,
        market_sentiment,
        comparative_data
    )
    
    # 2. Apply print-specific CSS rules to ensure it maps perfectly to A4
    print_css = CSS(string='''
        @page { 
            size: A4; 
            margin: 15mm; 
            @bottom-center {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 8pt;
                color: #64748b;
            }
        }
        body { 
            background: white !important; 
            padding: 0 !important; 
        }
        .page { 
            box-shadow: none !important; 
            margin: 0 !important; 
            padding: 0 !important; 
            border-radius: 0 !important; 
            width: 100% !important; 
            min-height: auto !important; 
            page-break-after: always; 
        }
        .page::after { display: none !important; }
    ''')
    
    # 3. Generate PDF
    buffer = BytesIO()
    HTML(string=html_content).write_pdf(buffer, stylesheets=[print_css])
    buffer.seek(0)
    return buffer


def generate_html_preview(
    property_data: dict,
    valuation_data: dict,
    report_config: dict,
    user_email: str,
    market_sentiment: dict = None,
    comparative_data: dict = None,
    sentiment_error: str = None,
    comparative_error: str = None
) -> tuple[str, int]:
    """
    Generate an HTML preview of the valuation report for interactive display.
    Returns HTML string that can be displayed in an iframe.
    """
    predicted_price = valuation_data.get('predicted_price', 0)
    confidence_interval = valuation_data.get('confidence_interval', [0, 0])
    interval_title, interval_note = interval_description(valuation_data)
    amenities = valuation_data.get('amenities', {})
    report_date = datetime.now().strftime("%d %B %Y")
    report_id = f"RPT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Get logo as base64 data URI
    logo_data_uri = get_logo_base64()

    # Count pages based on enabled sections
    pages = []

    # Page 1: Header, Executive Summary, and possibly more
    page1_content = []

    # Header section with actual logo
    page1_content.append(f'''
        <div class="header-section">
            <div class="logo-container">
                <img src="{logo_data_uri}" alt="HomeyAI Logo" class="logo-image" />
            </div>
            <h1 class="report-title">Property Valuation Report</h1>
            <p class="report-subtitle">Prepared by HomeyAI Valuation Services</p>
            <div class="separator"></div>
        </div>
    ''')
    
    # Metadata
    page1_content.append(f'''
        <div class="metadata-section">
            <table class="metadata-table">
                <tr>
                    <td class="label">Report Reference:</td>
                    <td class="value">{report_id}</td>
                    <td class="label">Valuation Date:</td>
                    <td class="value">{report_date}</td>
                </tr>
                <tr>
                    <td class="label">Prepared For:</td>
                    <td class="value">{user_email}</td>
                    <td class="label">Property Type:</td>
                    <td class="value">{property_data.get('flat_type', 'N/A')}</td>
                </tr>
                <tr>
                    <td class="label">Postal Code:</td>
                    <td class="value">{property_data.get('postal_code', 'N/A')}</td>
                    <td class="label">Floor Area:</td>
                    <td class="value">{property_data.get('floor_area_sqm', 0)} sqm</td>
                </tr>
            </table>
        </div>
    ''')
    
    # Executive Summary
    page1_content.append(f'''
        <div class="section">
            <h2 class="section-heading">EXECUTIVE SUMMARY</h2>
            <div class="executive-summary-grid">
                <div class="summary-box">
                    <div class="summary-label">ESTIMATED VALUATION</div>
                    <div class="summary-value" style="color: #2563eb;">S${predicted_price:,.0f}</div>
                </div>
                <div class="summary-box">
                    <div class="summary-label">{interval_title.upper()}</div>
                    <div class="summary-value" style="font-size: 1.2rem;">S${confidence_interval[0]:,.0f} - S${confidence_interval[1]:,.0f}</div>
                </div>
            </div>
        </div>
    ''')

    # Market Sentiment
    if report_config.get('include_market_sentiment'):
        if market_sentiment:
            rsi_qoq = market_sentiment.get('rsi_qoq_pct', 0)
            rsi_color = '#ef4444' if rsi_qoq < 0 else '#22c55e'
            rsi_sign = '+' if rsi_qoq >= 0 else ''
            
            page1_content.append(f'''
                <div class="section">
                    <h2 class="section-heading">MARKET INTELLIGENCE</h2>
                    <div style="background: #f8fafc; padding: 15px; border-radius: 8px; border-left: 4px solid #1a365d; margin-bottom: 15px;">
                        <p style="margin: 0; font-size: 0.95rem; line-height: 1.6; color: #1e293b;">
                            <strong>Market signal summary:</strong> {market_sentiment.get('composite_insight', 'Data unavailable.')}
                        </p>
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px;">
                        <div style="text-align: center; border: 1px solid #e2e8f0; padding: 10px; border-radius: 6px;">
                            <div style="font-size: 0.7rem; color: #64748b; text-transform: uppercase;">Price Index</div>
                            <div style="font-weight: bold; color: #1a365d;">{market_sentiment.get('rsi_raw', 'N/A')}</div>
                            <div style="font-size: 0.75rem; color: {rsi_color};">
                                {rsi_sign}{rsi_qoq}% QoQ
                            </div>
                        </div>
                        <div style="text-align: center; border: 1px solid #e2e8f0; padding: 10px; border-radius: 6px;">
                            <div style="font-size: 0.7rem; color: #64748b; text-transform: uppercase;">Interest Rate</div>
                            <div style="font-weight: bold; color: #1a365d;">{str(market_sentiment['interest_rate']) + '%' if market_sentiment.get('interest_rate') is not None else 'Unavailable'}</div>
                            <div style="font-size: 0.75rem; color: #64748b;">{market_sentiment.get('interest_rate_label') or 'No rate data'}</div>
                        </div>
                        <div style="text-align: center; border: 1px solid #e2e8f0; padding: 10px; border-radius: 6px;">
                            <div style="font-size: 0.7rem; color: #64748b; text-transform: uppercase;">Txn Volume</div>
                            <div style="font-weight: bold; color: #1a365d;">{market_sentiment.get('txn_volume', 'N/A')}</div>
                            <div style="font-size: 0.75rem; color: #64748b;">{market_sentiment.get('txn_volume_label', 'Normal')}</div>
                        </div>
                    </div>
                </div>
            ''')
        else:
            page1_content.append(f'''
                <div class="section">
                    <h2 class="section-heading">MARKET INTELLIGENCE</h2>
                    <div style="background: #f8fafc; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center;">
                        <p style="margin: 0; font-size: 0.9rem; color: #64748b;">
                            Market signals are unavailable for this report. Additional data or credentials may be required.
                        </p>
                    </div>
                </div>
            ''')
    
    # Valuation Summary
    if report_config.get('include_valuation_summary', True):
        page1_content.append(f'''
            <div class="section">
                <h2 class="section-heading">VALUATION SUMMARY</h2>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th class="header-cell">METRIC</th>
                            <th class="header-cell">VALUATION (SGD)</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td class="label-cell">Estimated Market Value</td><td class="value-cell">S$ {predicted_price:,.2f}</td></tr>
                        <tr><td class="label-cell">Lower range bound</td><td class="value-cell">S$ {confidence_interval[0]:,.2f}</td></tr>
                        <tr><td class="label-cell">Upper range bound</td><td class="value-cell">S$ {confidence_interval[1]:,.2f}</td></tr>
                    </tbody>
                </table>
                <p class="body-text">{interval_note}</p>
            </div>
        ''')
    
    # Property Details
    if report_config.get('include_property_details', True):
        page1_content.append(f'''
            <div class="section">
                <h2 class="section-heading">PROPERTY SPECIFICATIONS</h2>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th class="header-cell">ATTRIBUTE</th>
                            <th class="header-cell">SPECIFICATION</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td class="label-cell">Property Type</td><td class="value-cell">{property_data.get('flat_type', 'Not Specified')}</td></tr>
                        <tr><td class="label-cell">Postal Code</td><td class="value-cell">{property_data.get('postal_code', 'Not Specified')}</td></tr>
                        <tr><td class="label-cell">Floor Area</td><td class="value-cell">{property_data.get('floor_area_sqm', 0):,.2f} square metres</td></tr>
                        <tr><td class="label-cell">Remaining Lease</td><td class="value-cell">{str(property_data.get('remaining_lease_years', property_data.get('remaining_lease', 'Not Specified')))} years</td></tr>
                        <tr><td class="label-cell">Storey Midpoint</td><td class="value-cell">{property_data.get('storey_midpoint', 'Not Specified')}</td></tr>
                    </tbody>
                </table>
            </div>
        ''')
    
    # Amenities
    if report_config.get('include_amenities', True):
        page1_content.append(f'''
            <div class="section">
                <h2 class="section-heading">LOCATION & NEARBY AMENITIES</h2>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th class="header-cell">AMENITY TYPE</th>
                            <th class="header-cell">DETAILS</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td class="label-cell">Nearest MRT Station</td><td class="value-cell">{amenities.get('mrt', 'Data not available')}</td></tr>
                        <tr><td class="label-cell">Nearest Educational Institution</td><td class="value-cell">{amenities.get('school', 'Data not available')}</td></tr>
                        <tr><td class="label-cell">Distance to CBD</td><td class="value-cell">{amenities.get('cbd_distance', 'Data not available')}</td></tr>
                    </tbody>
                </table>
            </div>
        ''')

    # AI Reasoning (SHAP Values)
    shap_rows = _shap_rows_for_report(valuation_data.get("shap_values"))
    if shap_rows:
        page1_content.append(f'''
            <div class="section">
                <h2 class="section-heading">AI REASONING (SHAP VALUES)</h2>
                <p class="body-text" style="margin-bottom: 12px;">
                    SHAP explains the model in log-price space. The SGD figures are approximate
                    individual effects relative to the model baseline; they do not add up to the final price.
                </p>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th class="header-cell">FEATURE</th>
                            <th class="header-cell">PRICE IMPACT (SGD)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(f"""<tr>
                            <td class="label-cell">{shap['feature']}</td>
                            <td class="value-cell" style="color: {'#10b981' if shap['contribution'] >= 0 else '#ef4444'}; font-weight: bold;">
                                {'+' if shap['contribution'] >= 0 else '-'}S${abs(shap['contribution']):,.2f}
                            </td>
                        </tr>""" for shap in shap_rows)}
                    </tbody>
                </table>
            </div>
        ''')

    pages.append(''.join(page1_content))
    
    # Comparative Analysis
    if report_config.get('include_comparative_analysis'):
        comp_content = [f'''
            <div class="header-section">
                <div class="logo-container">
                    <img src="{logo_data_uri}" alt="HomeyAI Logo" class="logo-image" />
                </div>
                <h1 class="report-title">Comparative Market Analysis</h1>
                <div class="separator"></div>
            </div>
        ''']
        
        recorded_comparison = valuation_data.get('neighbor_comparison') or {}
        recorded_sales = recorded_comparison.get('similar_properties') or []
        if recorded_comparison.get('status') == 'ok' and recorded_sales:
            comp_content.append(f'''
                <div class="section">
                    <h2 class="section-heading">MARKET COMPARABLES</h2>
                    <p style="font-size: 0.85rem; color: #64748b; margin-bottom: 20px;">
                        Recorded nearby HDB resale transactions selected independently of the model estimate.
                        Source: HDB recorded resale transactions, data.gov.sg. These historical sales are
                        comparison evidence; they do not calibrate the model or its prediction interval.
                    </p>
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th class="header-cell">LOCATION / STREET</th>
                                <th class="header-cell">SALE MONTH</th>
                                <th class="header-cell">AREA (SQM)</th>
                                <th class="header-cell">RECORDED PRICE</th>
                            </tr>
                        </thead>
                        <tbody>
            ''')
            
            for sale in recorded_sales:
                comp_content.append(f'''
                    <tr>
                        <td class="label-cell">{sale['address']}</td>
                        <td class="value-cell">{sale['sale_month']}</td>
                        <td class="value-cell">{sale['floor_area']}</td>
                        <td class="value-cell">S${sale['price']:,.0f}</td>
                    </tr>
                ''')
                
            comp_content.append(f'''
                        </tbody>
                    </table>
                </div>
                
                <div class="section" style="margin-top: 30px;">
                    <h2 class="section-heading">TOWN PERFORMANCE BENCHMARK</h2>
                    <div style="background: #1a365d; color: white; padding: 25px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center;">
                        <div style="text-align: center; flex: 1;">
                            <div style="font-size: 0.8rem; opacity: 0.8; text-transform: uppercase; margin-bottom: 5px;">Subject Town</div>
                            <div style="font-size: 1.5rem; font-weight: 800;">{property_data.get('town', 'N/A')}</div>
                        </div>
                        <div style="font-size: 2rem; font-weight: 200; opacity: 0.5;">|</div>
                        <div style="text-align: center; flex: 1;">
                            <div style="font-size: 0.8rem; opacity: 0.8; text-transform: uppercase; margin-bottom: 5px;">Matching recorded sales</div>
                            <div style="font-size: 1.2rem; font-weight: 600;">{len(recorded_sales)} shown</div>
                        </div>
                    </div>
                </div>
            ''')
        else:
            comp_content.append(f'''
                <div class="section">
                    <h2 class="section-heading">MARKET COMPARABLES</h2>
                    <div style="background: #f8fafc; padding: 30px; border-radius: 12px; border: 1px dashed #cbd5e0; text-align: center;">
                        <p style="margin: 0; font-size: 0.95rem; color: #64748b;">
                            No recorded nearby comparable sales are available for this valuation.
                            Recalculate with a resolved property to check matching sales.
                        </p>
                    </div>
                </div>
            ''')
            
        pages.append("".join(comp_content))

    # Page 2: Market Insights
    if report_config.get('include_market_insights', True):
        page2_content = []
        page2_content.append('''
            <div class="header-section">
                <h2 class="section-heading">MARKET ANALYSIS & INSIGHTS</h2>
            </div>
        ''')
        page2_content.append('''
            <div class="section">
                <p class="body-text">
                    This valuation has been derived using advanced machine learning algorithms trained on
                    historical transaction data from Singapore's residential property market. The analysis
                    uses the features of the active model. The local baseline includes HDB property
                    characteristics and location; unavailable MRT/POI feature sets are not implied by this report.
                </p>
                <p class="body-text">
                    Recorded comparable sales are provided as historical context. Their prices have not
                    been adjusted for differences in date, size, floor level or market conditions.
                </p>
                <p class="body-text">
                    The range methodology and observed coverage are stated in the valuation summary.
                    A heuristic range carries no statistical coverage claim. Calibrated ranges can lose
                    coverage as the market shifts.
                </p>
            </div>
        ''')
        # Keep the short methodology and disclaimer together in print.
    
    # Disclaimer Page
    disclaimer_page = []
    disclaimer_page.append('''
        <div class="header-section">
            <h2 class="section-heading">IMPORTANT DISCLAIMER</h2>
        </div>
        <div class="section disclaimer-section">
            <p class="disclaimer-text">
                This valuation report has been prepared by HomeyAI for informational and reference purposes only.
                This document does not constitute professional financial advice, investment advice, or a formal
                property appraisal.
            </p>
            <p class="disclaimer-text">
                HomeyAI expressly disclaims all warranties, whether express or implied, including but not limited
                to warranties of accuracy, completeness, or fitness for a particular purpose. The actual market
                value may differ materially from this estimate.
            </p>
            <p class="disclaimer-text">
                For formal valuation purposes, such as mortgage applications or legal proceedings, users are
                advised to engage a qualified professional valuer registered with the Singapore Institute of
                Surveyors and Valuers (SISV).
            </p>
        </div>
    ''')
    methodology = "".join(page2_content) if report_config.get('include_market_insights', True) else ""
    pages.append(methodology + "".join(disclaimer_page))

    css_content = _valuation_preview_css()

    html = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Valuation Report Preview</title>
        <style>
            {css_content}
        </style>
    </head>
    <body>
    '''
    
    for i, page_content in enumerate(pages, 1):
        # We wrap each page and ensure it starts with a clean div
        html += f'<div class="page" data-page-number="Page {i} of {len(pages)}">{page_content}'
        
        # Add footer to the very last page
        if i == len(pages):
            html += f'''
                <div class="footer" style="margin-top: 30px; padding-top: 15px; border-top: 1px solid #e2e8f0; text-align: center;">
                    <p style="font-size: 8px; color: #64748b;">
                        Copyright {datetime.now().year} HomeyAI Valuation Services. All rights reserved. | 
                        This is a computer-generated professional report preview.
                    </p>
                </div>
            '''
        html += '</div>'
    
    html += '''
        <script>
            // Ensure pages are responsive
            document.querySelectorAll('.page').forEach(page => {
                page.style.transition = 'transform 0.3s ease';
            });
        </script>
    </body>
    </html>
    '''
    
    return html, len(pages)
