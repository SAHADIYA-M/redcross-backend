-- ============================================================
-- RedCross Nexus — Synthetic Flood-Emergency Dataset (v2)
-- Matches schema_v2.sql (report_needs junction table)
-- Run AFTER schema_v2.sql
-- ============================================================

-- ---------- RESPONDERS ----------
INSERT INTO responders (responder_id, full_name, email, organization, role) VALUES
    ('11111111-1111-1111-1111-111111111111', 'Anju Menon', 'anju@keralaredcross.org', 'Kerala Red Cross', 'field_reporter'),
    ('22222222-2222-2222-2222-222222222222', 'Ravi Kumar', 'ravi@ndrf.gov.in', 'NDRF', 'field_reporter'),
    ('33333333-3333-3333-3333-333333333333', 'Fathima S.', 'fathima@keralaredcross.org', 'Kerala Red Cross', 'verifier');

-- ---------- LOCATIONS ----------
INSERT INTO locations (location_id, name, location_type, raw_location_text, latitude, longitude) VALUES
    ('aaaaaaaa-0001-0001-0001-000000000001', 'Govt. UP School, Ponnani', 'school', 'Govt. UP School near relief area', 10.7672, 75.9265),
    ('aaaaaaaa-0002-0002-0002-000000000002', 'Ponnani Relief Centre', 'relief_center', 'Relief centre, Ponnani', 10.7660, 75.9270),
    ('aaaaaaaa-0003-0003-0003-000000000003', 'Chalissery Road Bridge', 'road', 'Bridge near Chalissery', 10.7550, 76.6890),
    ('aaaaaaaa-0004-0004-0004-000000000004', 'Government Taluk Hospital, Ponnani', 'hospital', 'Taluk hospital Ponnani', 10.7690, 75.9280),
    ('aaaaaaaa-0005-0005-0005-000000000005', 'Ponnani Riverside Ward', 'village', 'Riverside ward, Ponnani', 10.7680, 75.9240);

-- ---------- FIELD REPORTS (raw_content only — no need/priority here anymore) ----------
INSERT INTO field_reports (report_id, source_type, raw_content, reporter_id, location_id, reported_at) VALUES
    ('b0000000-0000-0000-0000-000000000001', 'text', 'No drinking water available near Govt. UP School. Around 40 families affected.', '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0001-0001-0001-000000000001', '2026-09-18 10:32:00+05:30'),
    ('b0000000-0000-0000-0000-000000000002', 'text', 'People gathered near the school asking for drinking water.', '22222222-2222-2222-2222-222222222222', 'aaaaaaaa-0001-0001-0001-000000000001', '2026-09-18 10:41:00+05:30'),
    ('b0000000-0000-0000-0000-000000000003', 'text', 'Water tanker hasn''t arrived near the school relief point yet.', '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0001-0001-0001-000000000001', '2026-09-18 10:55:00+05:30'),
    ('b0000000-0000-0000-0000-000000000004', 'image', 'Photograph showing empty water containers lined up outside the school.', '22222222-2222-2222-2222-222222222222', 'aaaaaaaa-0001-0001-0001-000000000001', '2026-09-18 11:00:00+05:30'),
    ('b0000000-0000-0000-0000-000000000005', 'csv', 'Approximately 45 families need water near the relief centre.', '33333333-3333-3333-3333-333333333333', 'aaaaaaaa-0002-0002-0002-000000000002', '2026-09-18 11:14:00+05:30'),
    ('b0000000-0000-0000-0000-000000000006', 'text', 'Tanker arrived at relief centre. Water being distributed now.', '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0002-0002-0002-000000000002', '2026-09-18 12:30:00+05:30'),
    ('b0000000-0000-0000-0000-000000000007', 'text', 'Hospital reports shortage of basic medicines, especially for elderly patients.', '22222222-2222-2222-2222-222222222222', 'aaaaaaaa-0004-0004-0004-000000000004', '2026-09-18 09:10:00+05:30'),
    ('b0000000-0000-0000-0000-000000000008', 'text', 'Taluk hospital pharmacy running low on stock, ~60 patients affected.', '33333333-3333-3333-3333-333333333333', 'aaaaaaaa-0004-0004-0004-000000000004', '2026-09-18 09:25:00+05:30'),
    ('b0000000-0000-0000-0000-000000000009', 'image', 'Photograph of near-empty medicine shelves at Taluk hospital.', '22222222-2222-2222-2222-222222222222', 'aaaaaaaa-0004-0004-0004-000000000004', '2026-09-18 09:30:00+05:30'),
    ('b0000000-0000-0000-0000-00000000000a', 'text', 'Chalissery road bridge partially submerged, vehicles cannot cross.', '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0003-0003-0003-000000000003', '2026-09-18 08:15:00+05:30'),
    ('b0000000-0000-0000-0000-00000000000b', 'csv', 'Bridge closure reported, approx 200 people cut off from relief centre.', '22222222-2222-2222-2222-222222222222', 'aaaaaaaa-0003-0003-0003-000000000003', '2026-09-18 08:20:00+05:30'),
    ('b0000000-0000-0000-0000-00000000000c', 'text', 'Relief centre at capacity, families sleeping outside under tarpaulin.', '33333333-3333-3333-3333-333333333333', 'aaaaaaaa-0002-0002-0002-000000000002', '2026-09-18 13:00:00+05:30'),
    ('b0000000-0000-0000-0000-00000000000d', 'text', 'Need additional tents at Ponnani relief centre, ~30 families without shelter.', '11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0002-0002-0002-000000000002', '2026-09-18 13:10:00+05:30'),
    ('b0000000-0000-0000-0000-00000000000e', 'text', 'Minor road debris cleared near market junction, no injuries.', '22222222-2222-2222-2222-222222222222', NULL, '2026-09-18 07:00:00+05:30'),
    ('b0000000-0000-0000-0000-00000000000f', 'text', 'Local volunteers distributing snacks near bus stand.', '11111111-1111-1111-1111-111111111111', NULL, '2026-09-18 07:30:00+05:30'),
    -- NEW: multi-need example report, showcasing the report_needs fix
    ('b0000000-0000-0000-0000-000000000010', 'text', '20 families need water, 5 houses are damaged, and 3 people need medical attention in Ponnani riverside ward.', '33333333-3333-3333-3333-333333333333', 'aaaaaaaa-0005-0005-0005-000000000005', '2026-09-18 14:00:00+05:30');

-- ---------- REPORT_NEEDS (one row per need per report — this is the new table) ----------
INSERT INTO report_needs (report_need_id, report_id, need_id, priority_id, affected_population_estimate) VALUES
    ('d0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 1, 2, 40),
    ('d0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000002', 1, 2, NULL),
    ('d0000000-0000-0000-0000-000000000003', 'b0000000-0000-0000-0000-000000000003', 1, 2, NULL),
    ('d0000000-0000-0000-0000-000000000004', 'b0000000-0000-0000-0000-000000000004', 1, 2, NULL),
    ('d0000000-0000-0000-0000-000000000005', 'b0000000-0000-0000-0000-000000000005', 1, 2, 45),
    ('d0000000-0000-0000-0000-000000000006', 'b0000000-0000-0000-0000-000000000006', 1, 4, NULL),
    ('d0000000-0000-0000-0000-000000000007', 'b0000000-0000-0000-0000-000000000007', 4, 1, NULL),
    ('d0000000-0000-0000-0000-000000000008', 'b0000000-0000-0000-0000-000000000008', 4, 1, 60),
    ('d0000000-0000-0000-0000-000000000009', 'b0000000-0000-0000-0000-000000000009', 4, 1, NULL),
    ('d0000000-0000-0000-0000-00000000000a', 'b0000000-0000-0000-0000-00000000000a', 7, 2, NULL),
    ('d0000000-0000-0000-0000-00000000000b', 'b0000000-0000-0000-0000-00000000000b', 7, 2, 200),
    ('d0000000-0000-0000-0000-00000000000c', 'b0000000-0000-0000-0000-00000000000c', 3, 2, NULL),
    ('d0000000-0000-0000-0000-00000000000d', 'b0000000-0000-0000-0000-00000000000d', 3, 2, 30),
    ('d0000000-0000-0000-0000-00000000000e', 'b0000000-0000-0000-0000-00000000000e', 7, 4, NULL),
    ('d0000000-0000-0000-0000-00000000000f', 'b0000000-0000-0000-0000-00000000000f', 2, 4, NULL),
    -- Report 0010 has THREE needs — this is the multi-need demonstration:
    ('d0000000-0000-0000-0000-000000000101', 'b0000000-0000-0000-0000-000000000010', 1, 2, 20),   -- water, 20 families
    ('d0000000-0000-0000-0000-000000000102', 'b0000000-0000-0000-0000-000000000010', 3, 2, 5),    -- shelter, 5 houses
    ('d0000000-0000-0000-0000-000000000103', 'b0000000-0000-0000-0000-000000000010', 4, 1, 3);    -- medical, 3 people

-- ---------- AFFECTED_PEOPLE (now references report_need_id, not report_id) ----------
-- NOTE: d…0007 and d…000c rows removed — affected_population_estimate set to
-- NULL in report_needs above, so these affected_people rows are also dropped.
INSERT INTO affected_people (report_need_id, count_estimate, unit) VALUES
    ('d0000000-0000-0000-0000-000000000001', 40, 'families'),
    ('d0000000-0000-0000-0000-000000000005', 45, 'families'),
    ('d0000000-0000-0000-0000-000000000008', 60, 'people'),
    ('d0000000-0000-0000-0000-00000000000b', 200, 'people'),
    ('d0000000-0000-0000-0000-00000000000d', 30, 'families'),
    ('d0000000-0000-0000-0000-000000000101', 20, 'families'),
    ('d0000000-0000-0000-0000-000000000102', 5, 'households'),
    ('d0000000-0000-0000-0000-000000000103', 3, 'people');

-- ---------- EVIDENCE (unchanged — still tied to the whole report) ----------
INSERT INTO evidence (report_id, evidence_type, file_url, caption) VALUES
    ('b0000000-0000-0000-0000-000000000004', 'photo', 'https://example-storage/photos/empty_containers.jpg', 'Empty water containers outside school'),
    ('b0000000-0000-0000-0000-000000000009', 'photo', 'https://example-storage/photos/empty_shelves.jpg', 'Near-empty medicine shelves');

-- ---------- REPORT CLUSTERS ----------
INSERT INTO report_clusters (cluster_id, need_id, location_id, priority_id, estimated_affected, status, first_reported_at, latest_update_at) VALUES
    ('c0000000-0000-0000-0000-000000000001', 1, 'aaaaaaaa-0001-0001-0001-000000000001', 2, 45, 'needs_review', '2026-09-18 10:32:00+05:30', '2026-09-18 14:00:00+05:30'),
    ('c0000000-0000-0000-0000-000000000002', 4, 'aaaaaaaa-0004-0004-0004-000000000004', 1, 60, 'needs_review', '2026-09-18 09:10:00+05:30', '2026-09-18 14:00:00+05:30'),
    ('c0000000-0000-0000-0000-000000000003', 7, 'aaaaaaaa-0003-0003-0003-000000000003', 2, 200, 'needs_review', '2026-09-18 08:15:00+05:30', '2026-09-18 08:20:00+05:30'),
    ('c0000000-0000-0000-0000-000000000004', 3, 'aaaaaaaa-0002-0002-0002-000000000002', 2, 35, 'needs_review', '2026-09-18 13:00:00+05:30', '2026-09-18 14:00:00+05:30');

-- ---------- CLUSTER MEMBERS (now references report_need_id, not report_id) ----------
-- Water cluster: 5 supporting, 1 duplicate, 1 conflicting, plus the new multi-need report's water need
INSERT INTO cluster_members (cluster_id, report_need_id, relationship_type, relationship_score) VALUES
    ('c0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000001', 'supporting', 1.000),
    ('c0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000002', 'supporting', 0.910),
    ('c0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000003', 'supporting', 0.880),
    ('c0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000004', 'supporting', 0.860),
    ('c0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000005', 'potential_duplicate', 0.930),
    ('c0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000006', 'conflicting', 0.870),
    ('c0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000101', 'supporting', 0.780);

-- Medical cluster, now also receiving the multi-need report's medical need
INSERT INTO cluster_members (cluster_id, report_need_id, relationship_type, relationship_score) VALUES
    ('c0000000-0000-0000-0000-000000000002', 'd0000000-0000-0000-0000-000000000007', 'supporting', 1.000),
    ('c0000000-0000-0000-0000-000000000002', 'd0000000-0000-0000-0000-000000000008', 'potential_duplicate', 0.940),
    ('c0000000-0000-0000-0000-000000000002', 'd0000000-0000-0000-0000-000000000009', 'supporting', 0.870),
    ('c0000000-0000-0000-0000-000000000002', 'd0000000-0000-0000-0000-000000000103', 'unrelated', 0.310);

-- Bridge cluster
INSERT INTO cluster_members (cluster_id, report_need_id, relationship_type, relationship_score) VALUES
    ('c0000000-0000-0000-0000-000000000003', 'd0000000-0000-0000-0000-00000000000a', 'supporting', 1.000),
    ('c0000000-0000-0000-0000-000000000003', 'd0000000-0000-0000-0000-00000000000b', 'supporting', 0.890);

-- Shelter cluster, now also receiving the multi-need report's shelter need
INSERT INTO cluster_members (cluster_id, report_need_id, relationship_type, relationship_score) VALUES
    ('c0000000-0000-0000-0000-000000000004', 'd0000000-0000-0000-0000-00000000000c', 'supporting', 1.000),
    ('c0000000-0000-0000-0000-000000000004', 'd0000000-0000-0000-0000-00000000000d', 'potential_duplicate', 0.920),
    ('c0000000-0000-0000-0000-000000000004', 'd0000000-0000-0000-0000-000000000102', 'supporting', 0.740);

-- Reports 000e, 000f are intentionally left unclustered (unrelated / noise).

-- ============================================================
-- TEST CASE NOTES:
--
-- 1. DUPLICATE DETECTION: reports 002/005 (water), 007/008 (medical),
--    and 00c/00d (shelter) are each near-duplicate pairs your fusion
--    engine should catch as potential_duplicate, not brand-new needs.
--
-- 2. CONFLICT DETECTION: report 006 ("tanker arrived") must be classified
--    as CONFLICTING with the rest of the water cluster.
--
-- 3. MULTI-NEED HANDLING (new): report 0010 has THREE separate needs
--    (water, shelter, medical). Its three report_needs rows correctly
--    feed THREE different clusters — this is the exact scenario your
--    teammate flagged, and it's now testable.
--
-- 4. FALSE-POSITIVE CHECKS: reports 00e/00f stay unclustered. Report
--    0010's medical need (d...103) is deliberately marked 'unrelated'
--    to the existing medical cluster — its symptoms differ from the
--    hospital medicine-shortage cluster, so a good fusion engine should
--    NOT force it in just because both are "medical."
-- ============================================================
