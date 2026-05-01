-- Check if migrations applied
SELECT version, description FROM schema_migrations ORDER BY version DESC LIMIT 5;

-- Check sentiment_results schema (should have new columns)
\d sentiment_results

-- Check ner_results schema (should have new columns)  
\d ner_results
