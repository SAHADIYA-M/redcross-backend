-- ============================================================
-- RedCross Nexus — Query: Candidate report retrieval
-- Finds the top-5 most semantically similar OTHER reports for a
-- given input report, using pgvector cosine distance on embeddings.
--
-- Parameters:
--   %(report_id)s      UUID of the input report (always required)
--   %(need_id)s        SMALLINT — optional need filter (pass NULL to skip)
--   %(apply_filters)s  BOOLEAN  — TRUE  = enforce 72-hour and 2 km filters
--                                  FALSE = return top-5 by similarity only
-- ============================================================

WITH
input AS (
    SELECT
        fr.report_id,
        fr.embedding,
        fr.reported_at,
        fr.location_id,
        l.latitude  AS lat,
        l.longitude AS lng
    FROM field_reports fr
    LEFT JOIN locations l USING (location_id)
    WHERE fr.report_id = %(report_id)s::uuid
),

input_needs AS (
    SELECT rn.need_id, n.code AS need_code
    FROM report_needs rn
    JOIN needs n USING (need_id)
    JOIN input ON rn.report_id = input.report_id
    WHERE %(need_id)s::smallint IS NULL
       OR rn.need_id = %(need_id)s::smallint
),

candidates AS (
    SELECT
        fr.report_id,
        fr.raw_content,
        fr.reported_at,
        fr.location_id,
        l.name        AS location_name,
        l.latitude    AS lat,
        l.longitude   AS lng,
        (fr.embedding <=> (SELECT embedding FROM input)) AS cosine_dist,
        (
            6371.0 * 2 * asin(
                sqrt(
                    power(sin(radians((l.latitude  - (SELECT lat FROM input)) / 2)), 2)
                  + cos(radians((SELECT lat FROM input)))
                  * cos(radians(l.latitude))
                  * power(sin(radians((l.longitude - (SELECT lng FROM input)) / 2)), 2)
                )
            )
        ) AS distance_km,
        abs(extract(epoch FROM fr.reported_at - (SELECT reported_at FROM input))) / 3600.0
            AS hours_apart
    FROM field_reports fr
    JOIN locations l USING (location_id)
    JOIN input ON fr.report_id <> input.report_id
    WHERE fr.embedding IS NOT NULL
      AND fr.location_id IS NOT NULL
),

shared AS (
    SELECT
        c.report_id,
        string_agg(DISTINCT n.code::text, ', ' ORDER BY n.code::text) AS shared_need_codes
    FROM candidates c
    JOIN report_needs rn ON rn.report_id = c.report_id
    JOIN needs        n  USING (need_id)
    JOIN input_needs  iq ON iq.need_id = rn.need_id
    GROUP BY c.report_id
),

filtered AS (
    SELECT
        c.report_id,
        left(c.raw_content, 80)  AS snippet,
        1 - c.cosine_dist        AS similarity,
        round(c.distance_km::numeric, 3) AS distance_km,
        s.shared_need_codes      AS shared_needs,
        c.location_name
    FROM candidates c
    JOIN shared s USING (report_id)
    WHERE
        (NOT %(apply_filters)s::boolean OR (
            c.hours_apart <= 72
            AND (
                c.location_id = (SELECT location_id FROM input)
                OR c.distance_km <= 2.0
            )
        ))
    ORDER BY c.cosine_dist ASC
    LIMIT 5
)

SELECT * FROM filtered;
