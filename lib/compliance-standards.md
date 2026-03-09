# Regulatory Compliance Standards Reference

## GDPR (General Data Protection Regulation)

### Key Articles

| Article  | Requirement                                         | Severity |
|----------|-----------------------------------------------------|----------|
| Art. 5   | Data processing principles (lawfulness, minimization)| Critical |
| Art. 6   | Lawful basis for processing                          | Critical |
| Art. 7   | Conditions for consent (clear, specific, revocable)  | Critical |
| Art. 12  | Transparent information and communication            | High     |
| Art. 13  | Information at point of collection                   | High     |
| Art. 14  | Information for indirectly obtained data             | High     |
| Art. 15  | Right of access                                      | High     |
| Art. 16  | Right to rectification                               | High     |
| Art. 17  | Right to erasure (right to be forgotten)             | Critical |
| Art. 20  | Right to data portability                            | Medium   |
| Art. 25  | Data protection by design and default                | High     |
| Art. 32  | Security of processing (encryption, pseudonymization)| Critical |
| Art. 33  | Breach notification to authority (72 hours)           | Critical |
| Art. 34  | Breach notification to data subjects                 | Critical |
| Art. 35  | Data protection impact assessment                    | High     |
| Art. 44  | Cross-border transfer restrictions                   | High     |

### Code Checks

| Check                        | What to Look For                                    |
|------------------------------|-----------------------------------------------------|
| Cookie consent               | Banner present, opt-in (not opt-out), granular      |
| Privacy policy               | Linked from every page, comprehensive               |
| Consent storage              | Consent recorded with timestamp and scope            |
| Data deletion                | API/code path to delete user data on request         |
| Data export                  | API/code path to export user data (JSON/CSV)         |
| Data minimization            | Only necessary fields collected                      |
| Retention policies           | TTLs on stored data, cleanup jobs                    |
| Encryption                   | PII encrypted at rest, TLS in transit                |
| Third-party sharing          | Documented and consented                             |
| DPO contact                  | Accessible from privacy policy                       |

## ISO 27001 — Information Security

### Annex A Controls

| Control  | Area                    | Key Requirements                              |
|----------|-------------------------|-----------------------------------------------|
| A.5      | Security policies       | Documented and reviewed                       |
| A.6      | Organization            | Roles and responsibilities defined             |
| A.8      | Asset management        | Data classified and inventoried                |
| A.9      | Access control          | Least privilege, MFA, session management       |
| A.10     | Cryptography            | Encryption policy, key management              |
| A.12     | Operations security     | Logging, monitoring, change management         |
| A.13     | Communications security | Network controls, data transfer security       |
| A.14     | System development      | Secure development lifecycle                   |
| A.16     | Incident management     | Incident response plan, logging                |
| A.18     | Compliance              | Legal and regulatory compliance                |

### Code Checks

| Check                        | What to Look For                                    |
|------------------------------|-----------------------------------------------------|
| Security headers             | CSP, HSTS, X-Frame-Options, X-Content-Type-Options  |
| Authentication               | Strong passwords, MFA support, account lockout       |
| Authorization                | Role-based access, least privilege                   |
| Encryption at rest           | Database encryption, encrypted secrets               |
| Encryption in transit        | TLS 1.2+, no mixed content                          |
| Audit logging                | Auth events, data access, admin actions logged       |
| Input validation             | All user inputs validated and sanitized              |
| Session management           | Secure tokens, expiration, invalidation              |
| Rate limiting                | API rate limits, brute force protection              |
| Error handling               | No stack traces or internal info in errors           |
| Dependency security          | No known CVEs in dependencies                        |

## Age Verification Laws

### United States

| Law                          | State      | Effective    | Applies To                           | Requirement                    |
|------------------------------|------------|--------------|--------------------------------------|--------------------------------|
| Act 440                      | Louisiana  | Jan 2024     | Adult content sites                  | Age verification required      |
| S.B. 152                     | Utah       | Mar 2024     | Social media platforms               | Age verification for minors    |
| HB 1181                      | Texas      | Sep 2023     | Adult content sites                  | Age verification required      |
| SB 1515                      | Virginia   | Jul 2024     | Adult content sites                  | Age verification required      |
| Social Media Safety Act      | Arkansas   | Sep 2023     | Social media platforms               | Age verification for minors    |
| AADC (AB 2273)               | California | Jul 2024     | Online services likely used by kids  | Privacy by default for minors  |
| SB 384                       | Montana    | Jan 2024     | Social media platforms               | Ban for users under 16         |

### United Kingdom

| Law                          | Effective    | Applies To                           | Requirement                    |
|------------------------------|--------------|--------------------------------------|--------------------------------|
| Online Safety Act (OSA)      | 2024-2025    | User-to-user & search services       | Age verification for harmful content |
| OSA Part 5                   | 2024         | Pornographic content providers       | Robust age verification        |
| ICO Age Appropriate Design   | Sep 2021     | Services likely accessed by children | 15 standards for child safety  |
| Ofcom codes of practice      | 2024-2025    | Regulated services                   | Content moderation, age checks |

### Code Checks

| Check                        | What to Look For                                    |
|------------------------------|-----------------------------------------------------|
| Age gate UI                  | Modal/page requiring age confirmation                |
| Verification API             | Integration with age verification provider           |
| Content classification       | System to categorize content by age-appropriateness  |
| Parental consent             | Mechanism for parental verification for minors       |
| Minor data protection        | Enhanced privacy for users identified as minors      |
| Geo-detection                | IP-based or user-selected jurisdiction detection     |
| Consent records              | Age verification consent stored with timestamp       |

## Compliance Scoring

| Score     | Status          | Description                                      |
|-----------|-----------------|--------------------------------------------------|
| 90-100    | Compliant       | Meets all requirements                           |
| 70-89     | Partial         | Most requirements met, minor gaps                |
| 50-69     | At Risk         | Significant gaps, remediation needed             |
| Below 50  | Non-Compliant   | Major compliance failures, legal risk            |
