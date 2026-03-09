# SEO Standards Reference

## Technical SEO Essentials

| Check                    | Requirement                                           | Severity |
|--------------------------|-------------------------------------------------------|----------|
| Meta title               | Present on every page, 50-60 chars, unique per page   | Critical |
| Meta description         | Present on every page, 150-160 chars, unique          | High     |
| Canonical URL            | Self-referencing canonical on every page               | High     |
| robots.txt               | Present at root, not blocking important paths          | Critical |
| sitemap.xml              | Present, valid XML, lists all indexable URLs            | High     |
| H1 tag                   | Exactly one per page                                   | High     |
| Heading hierarchy        | Logical nesting (H1 > H2 > H3), no skipped levels     | Medium   |
| URL structure            | Descriptive slugs, lowercase, hyphens not underscores  | Medium   |
| HTTPS                    | All pages served over HTTPS                            | Critical |
| Mobile viewport          | `<meta name="viewport">` present                       | Critical |
| Page speed               | Images optimized, CSS/JS minified, lazy loading        | High     |

## Structured Data / Schema.org

| Type              | When to Use                    | Priority |
|-------------------|--------------------------------|----------|
| Organization      | Company/brand pages            | High     |
| WebSite           | Homepage                       | High     |
| BreadcrumbList    | All pages with breadcrumbs     | Medium   |
| Article           | Blog/news content              | Medium   |
| Product           | E-commerce product pages       | High     |
| FAQPage           | FAQ sections                   | High     |
| LocalBusiness     | Local business sites           | High     |
| HowTo             | Tutorial/guide content         | Medium   |

## AI Search Optimization

| Signal                        | Description                                           |
|-------------------------------|-------------------------------------------------------|
| Direct answers                | Content answers questions in the first paragraph      |
| Semantic HTML                 | Proper use of article, section, nav, main, aside      |
| FAQ markup                    | Schema.org FAQPage for Q&A content                    |
| Entity clarity                | Clear subject-predicate-object content structure       |
| Factual density               | Verifiable facts, statistics, citations                |
| Content freshness             | Last-modified dates, publication dates visible         |
| Conversational content        | Natural language that AI assistants can quote          |

## Social Meta Tags

| Tag                          | Requirement                                           |
|------------------------------|-------------------------------------------------------|
| og:title                     | Present, matches or enhances page title               |
| og:description               | Present, compelling summary                           |
| og:image                     | Present, 1200x630px minimum                           |
| og:url                       | Canonical URL                                         |
| og:type                      | Appropriate type (website, article, product)           |
| twitter:card                 | summary_large_image preferred                         |
| twitter:title                | Present                                               |
| twitter:description          | Present                                               |
| twitter:image                | Present                                               |

## Scoring

- **90-100**: Excellent SEO health
- **70-89**: Good, minor improvements needed
- **50-69**: Fair, significant issues to address
- **Below 50**: Poor, critical SEO problems
