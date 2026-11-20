-- Built-in category tree (owner_id null), from CATEGORIES in the intake feasibility test
-- (CS-452 Database/26-11-16 collection intake feasibility/intake.py).
-- Brands and platforms are attributes, not categories. Children inherit their parents' fields.
-- A migration rather than seed.sql because production needs these rows too; seed.sql only runs locally.

with top_level (name, field_template) as (values
  ('Video Games', '[{"key":"platform","label":"Platform","type":"text"},
                    {"key":"region","label":"Region","type":"text"}]'::jsonb),
  ('Movies & TV', '[]'),
  ('Books', '[{"key":"author","label":"Author","type":"text"},
              {"key":"isbn","label":"ISBN","type":"text"}]'),
  ('Board Games & Puzzles', '[{"key":"publisher","label":"Publisher","type":"text"},
                              {"key":"player_count","label":"Players","type":"text"},
                              {"key":"piece_count","label":"Pieces","type":"number"},
                              {"key":"complete","label":"All pieces present","type":"boolean"}]'),
  ('Toys & Building Sets', '[{"key":"brand","label":"Brand","type":"text"},
                            {"key":"set_number","label":"Set number","type":"text"},
                            {"key":"piece_count","label":"Pieces","type":"number"}]'),
  ('Music', '[]'),
  ('Collectibles & Memorabilia', '[{"key":"franchise","label":"Franchise","type":"text"},
                                  {"key":"numbered","label":"Number / edition size","type":"text"}]'),
  ('Home Decor', '[]'),
  ('Kitchen', '[{"key":"brand","label":"Brand","type":"text"}]'),
  ('Bags & Cases', '[{"key":"brand","label":"Brand","type":"text"},
                    {"key":"color","label":"Color","type":"text"},
                    {"key":"material","label":"Material","type":"text"}]'),
  ('Clothing & Textiles', '[{"key":"brand","label":"Brand","type":"text"},
                           {"key":"size","label":"Size","type":"text"},
                           {"key":"color","label":"Color","type":"text"},
                           {"key":"material","label":"Material","type":"text"}]'),
  ('Tools', '[{"key":"brand","label":"Brand","type":"text"}]'),
  ('Electronics', '[{"key":"brand","label":"Brand","type":"text"},
                   {"key":"model","label":"Model","type":"text"}]'),
  ('Other', '[]')
)
insert into public.categories (owner_id, parent_id, name, field_template)
select null, null, name, field_template from top_level
on conflict do nothing;

with child (parent, name, field_template) as (values
  ('Video Games', 'Games', '[{"key":"edition","label":"Edition","type":"text"},
                            {"key":"complete_in_box","label":"Complete in box","type":"boolean"}]'::jsonb),
  ('Video Games', 'Consoles', '[{"key":"model","label":"Model","type":"text"},
                               {"key":"color","label":"Color / edition","type":"text"},
                               {"key":"storage","label":"Storage","type":"text"}]'),
  ('Video Games', 'Controllers', '[{"key":"model","label":"Model","type":"text"},
                                  {"key":"color","label":"Color / edition","type":"text"}]'),
  ('Video Games', 'Accessories', '[]'),
  ('Movies & TV', 'Physical media', '[{"key":"format","label":"Format","type":"choice",
                                      "options":["4K UHD","Blu-ray","DVD","VHS","Other"]},
                                     {"key":"edition","label":"Edition","type":"text"},
                                     {"key":"packaging","label":"Packaging","type":"choice",
                                      "options":["Standard case","Steelbook","Slipcover","Box set","Other"]},
                                     {"key":"disc_count","label":"Discs","type":"number"},
                                     {"key":"region","label":"Region","type":"text"}]'),
  ('Books', 'Novels', '[{"key":"format","label":"Format","type":"choice",
                        "options":["Hardcover","Paperback","Mass market","Other"]},
                       {"key":"edition","label":"Edition","type":"text"}]'),
  ('Books', 'Manga & Comics', '[{"key":"volume","label":"Volume","type":"number"},
                               {"key":"publisher","label":"Publisher","type":"text"}]'),
  ('Books', 'Other', '[]'),
  ('Music', 'Instruments', '[{"key":"brand","label":"Brand","type":"text"},
                            {"key":"model","label":"Model","type":"text"}]'),
  ('Music', 'Albums & Vinyl', '[{"key":"artist","label":"Artist","type":"text"},
                               {"key":"format","label":"Format","type":"choice",
                                "options":["Vinyl","CD","Cassette","Other"]},
                               {"key":"pressing","label":"Pressing / variant","type":"text"}]'),
  ('Home Decor', 'Wall art & Frames', '[{"key":"artist","label":"Artist","type":"text"},
                                       {"key":"medium","label":"Medium","type":"text"},
                                       {"key":"dimensions","label":"Dimensions","type":"text"}]'),
  ('Home Decor', 'Seasonal', '[{"key":"season","label":"Holiday / season","type":"text"}]'),
  ('Home Decor', 'Candles & Fragrance', '[{"key":"scent","label":"Scent","type":"text"},
                                         {"key":"size","label":"Size","type":"text"}]'),
  ('Home Decor', 'Other', '[]'),
  ('Kitchen', 'Appliances', '[{"key":"model","label":"Model","type":"text"},
                             {"key":"color","label":"Color","type":"text"}]'),
  ('Kitchen', 'Drinkware & Dishes', '[{"key":"material","label":"Material","type":"text"},
                                     {"key":"piece_count","label":"Pieces","type":"number"}]'),
  ('Tools', 'Tool sets', '[{"key":"piece_count","label":"Pieces","type":"number"},
                          {"key":"model","label":"Model / set number","type":"text"}]'),
  ('Tools', 'Hand & Power tools', '[{"key":"model","label":"Model","type":"text"},
                                   {"key":"power","label":"Power","type":"choice",
                                    "options":["Corded","Cordless","Manual"]}]'),
  ('Electronics', 'Other', '[]')
)
insert into public.categories (owner_id, parent_id, name, field_template)
select null, p.id, child.name, child.field_template
from child
join public.categories p on p.name = child.parent and p.owner_id is null and p.parent_id is null
on conflict do nothing;
