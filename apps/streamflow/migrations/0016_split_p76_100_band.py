"""
Split the single ``p76_100`` band into five finer-grained bands
(``p76_85``, ``p86_90``, ``p91_95``, ``p96_98``, ``p99_100``) so the
downstream dashboard can colour the upper range of the flow distribution
with more resolution.

The reclassification is done in-place against ``daily_flow_percentiles``
using the ``percentile_rank`` already stored on each row.
"""

from django.db import migrations, models


BAND_CHOICES = [
    ("p0_4",    "Very Low (0–4th percentile)"),
    ("p5_10",   "Low (5th–10th percentile)"),
    ("p11_25",  "Below Normal (11th–25th percentile)"),
    ("p26_50",  "Normal (26th–50th percentile)"),
    ("p51_75",  "Above Normal (51st–75th percentile)"),
    ("p76_85",  "High (76th–85th percentile)"),
    ("p86_90",  "Very High (86th–90th percentile)"),
    ("p91_95",  "Extreme (91st–95th percentile)"),
    ("p96_98",  "Severe (96th–98th percentile)"),
    ("p99_100", "Exceptional (>98th percentile)"),
]


RECLASSIFY_FORWARD = """
    UPDATE daily_flow_percentiles
    SET band = CASE
        WHEN percentile_rank <= 85 THEN 'p76_85'
        WHEN percentile_rank <= 90 THEN 'p86_90'
        WHEN percentile_rank <= 95 THEN 'p91_95'
        WHEN percentile_rank <= 98 THEN 'p96_98'
        ELSE 'p99_100'
    END
    WHERE band = 'p76_100'
"""

RECLASSIFY_REVERSE = """
    UPDATE daily_flow_percentiles
    SET band = 'p76_100'
    WHERE band IN ('p76_85', 'p86_90', 'p91_95', 'p96_98', 'p99_100')
"""


class Migration(migrations.Migration):

    dependencies = [
        ("streamflow", "0015_daily_flow_percentile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dailyflowpercentile",
            name="band",
            field=models.CharField(choices=BAND_CHOICES, max_length=10),
        ),
        migrations.RunSQL(
            sql=RECLASSIFY_FORWARD,
            reverse_sql=RECLASSIFY_REVERSE,
        ),
    ]
