Tile tools (durable copies; job tmp dirs vanish after /clear). Run from anywhere with python.
 preflight_scan.py <lat/lon> [from to minkm2]  dup/missing numbers, types, Type 2 list, type-1 dots, independent overlap scan (no registry filter)
 type2_list.py                                 edit tile inside; Type 2 entries with area/compactness/enclave hosts
 paint.py <lat/lon> <year> <lon> <lat>         who covers a point at a year (file order, last = on top); or ... <year> --rep <entry#>
Registry audit: python audit_registry_exclusions.py --tiles 120:110 ; copy exports/registry_exclusion_audit.csv to exports/targeted<tile>/ ; git checkout -- exports/registry_exclusion_audit.csv
 parents.py <lat/lon> <entry#...>   finds the real parents/neighbours of an entry for a carve test
