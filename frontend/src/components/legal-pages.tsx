import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { LEGAL } from "@/lib/legal";

import styles from "./marketing-home.module.css";

function LegalLayout({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className={styles.root}>
    <SiteHeader active="none"/>
    <main className="legal-page container">
      <span className="eyebrow">LEGAL</span>
      <h1>{title}</h1>
      <p className="legal-updated">Effective {LEGAL.effectiveDate}</p>
      {children}
    </main>
    <SiteFooter/>
  </div>;
}

const Mail = () => <a href={`mailto:${LEGAL.contactEmail}`}>{LEGAL.contactEmail}</a>;

export function TermsPage() {
  const { brand, company, website, governingState } = LEGAL;
  return <LegalLayout title="Terms of Service">
    <p>These Terms govern your use of {brand} ({website}), operated by {company} (&quot;we&quot;, &quot;us&quot;). By creating an account or using the service you agree to them. If you do not agree, do not use the service.</p>

    <h2>1. What the service is</h2>
    <p>{brand} gathers publicly available information about sheriff, clerk, court and public trustee foreclosure sales and adds estimates and research signals: estimated market values, minimum bids, gross equity, the probability a sale goes ahead, preliminary lien screening, photos and maps. It is a research tool for investors.</p>

    <h2>2. Information only — not advice</h2>
    <p>Everything on the service is provided for information only. It is not legal, financial, tax, investment or title advice, and it is not a title search or a guarantee of lien status.</p>
    <ul>
      <li>Listings come from public and third-party sources that can be incomplete, delayed or wrong. Sales are often postponed, cancelled or changed, sometimes on the day.</li>
      <li>Values, equity, probabilities and photos are automated estimates and may differ significantly from reality.</li>
      <li>You are responsible for verifying every property, its liens and the current sale terms with the official source, and for getting a professional title search and your own legal and financial advice, before you bid or buy.</li>
    </ul>

    <h2>3. Accounts</h2>
    <p>You must be at least 18 and provide accurate information. Keep your login secure; you are responsible for activity on your account. One account is for one person; do not share it.</p>

    <h2>4. Plans, billing and cancellation</h2>
    <ul>
      <li>Paid plans (Starter and Pro) are subscriptions billed in advance, monthly or yearly, through our payment processor, Stripe. They renew automatically until cancelled.</li>
      <li>You can cancel at any time from your account (Manage billing). Your plan stays active until the end of the period you have paid for. Except where the law requires, payments are non-refundable and we do not give credits for partial periods.</li>
      <li>Each plan covers the area described on our pricing page (for example one county, one state, or every state we cover). We may change prices or plan features with notice; changes apply from your next billing period.</li>
      <li>If a payment fails, access to paid features may be paused until it is resolved.</li>
    </ul>

    <h2>5. Acceptable use</h2>
    <p>You may use the service for your own investment research. You may not:</p>
    <ul>
      <li>copy, scrape, export in bulk, resell, republish or redistribute the data or the service, or build a competing product from it;</li>
      <li>get around plan limits, rate limits or security, or access accounts or data that are not yours;</li>
      <li>use the service to harass, contact or discriminate against property owners or occupants, or for any unlawful purpose.</li>
    </ul>
    <p>We may suspend or close accounts that break these rules.</p>

    <h2>6. Our content and your data</h2>
    <p>The service, its software, design, compilations and estimates belong to us or our licensors. Public records remain public; our selection, enrichment and presentation of them are ours. You keep ownership of what you give us (such as your investor profile), and you let us use it to run the service as described in our <a href="/privacy">Privacy Policy</a>.</p>

    <h2>7. Third-party services and links</h2>
    <p>We rely on and link to third parties, including county and court websites, Stripe, Zillow and Google. We are not responsible for their content, availability or terms.</p>

    <h2>8. Availability and changes</h2>
    <p>We work to keep the service available and accurate but do not promise it will be uninterrupted, error-free or cover every sale. We may change, add or remove features and data sources.</p>

    <h2>9. Disclaimer of warranties</h2>
    <p>The service is provided &quot;as is&quot; and &quot;as available&quot;, without warranties of any kind, express or implied, including accuracy, completeness, merchantability, fitness for a particular purpose and non-infringement, to the fullest extent the law allows.</p>

    <h2>10. Limitation of liability</h2>
    <p>To the fullest extent the law allows, {company} is not liable for any indirect, incidental, special, consequential or punitive damages, or for lost profits, lost investments or losses from bidding on or buying property, arising from your use of the service. Our total liability for any claim is limited to the amount you paid us in the 12 months before the claim.</p>

    <h2>11. Indemnity</h2>
    <p>You agree to indemnify us against claims arising from your misuse of the service or your breach of these Terms.</p>

    <h2>12. Ending your use</h2>
    <p>You can stop using the service and close your account at any time by contacting us. We may suspend or end access for breach of these Terms. Sections that by their nature should survive (such as 2, 6, 9, 10 and 11) survive.</p>

    <h2>13. Governing law</h2>
    <p>These Terms are governed by the laws of the State of {governingState}, without regard to its conflict-of-law rules. Disputes will be resolved in the state or federal courts located in {governingState}, unless the law requires otherwise.</p>

    <h2>14. Changes to these Terms</h2>
    <p>We may update these Terms. We will post the new version here with a new effective date and, for material changes, notify you by email or in the service. Continuing to use the service after that means you accept the changes.</p>

    <h2>15. Contact</h2>
    <p>{company}, {LEGAL.postalAddress}. Email: <Mail/>.</p>
  </LegalLayout>;
}

export function PrivacyPage() {
  const { brand, company } = LEGAL;
  return <LegalLayout title="Privacy Policy">
    <p>This policy explains what personal information {company} (&quot;we&quot;) collects through {brand}, how we use it, and your choices.</p>

    <h2>1. Information we collect</h2>
    <ul>
      <li><b>Account details:</b> your email address and password (stored by our sign-in provider; we never see your password), and your name if you give it.</li>
      <li><b>Plan and billing:</b> your plan, coverage area and billing status. Card details are collected and stored by Stripe, not by us.</li>
      <li><b>Investor profile (optional):</b> your budget, states, strategy, property types, timeframe, financing, experience, notes and email-alert choices.</li>
      <li><b>Messages:</b> what you send through our contact form, with your name and email.</li>
      <li><b>Technical data:</b> IP address, browser and device information, and request logs our hosting providers keep for security and reliability. We use your browser&apos;s storage to keep you signed in and to remember small preferences; we do not use advertising cookies.</li>
    </ul>

    <h2>2. Public-record property information</h2>
    <p>The service shows information from public records and public notices about properties and foreclosure sales, which can include the names of parties to a court case. We show it for property research only. If you believe information about you is inaccurate, contact us and we will review it.</p>

    <h2>3. How we use information</h2>
    <ul>
      <li>To provide the service: sign-in, your plan and coverage, billing and support.</li>
      <li>To send account emails (confirmations, password resets, billing notices).</li>
      <li>To send opportunity emails matched to your investor profile, only if you turn them on. Every one has an unsubscribe link, and you can turn them off on your profile page.</li>
      <li>To keep the service secure, prevent abuse and enforce our Terms.</li>
      <li>To understand and improve the service.</li>
    </ul>
    <p>We do not sell your personal information, and we do not share it for others&apos; advertising.</p>

    <h2>4. Service providers</h2>
    <p>We share information only with providers that run the service for us, under their own security and privacy commitments:</p>
    <ul>
      <li>Supabase (database and sign-in) and Railway (hosting);</li>
      <li>Stripe (payments);</li>
      <li>Resend (sending email) and Zoho (our email inbox);</li>
      <li>Google (Street View photos) and Apify (property value lookups) — these receive property addresses, not your personal details;</li>
      <li>GitHub (scheduled data jobs).</li>
    </ul>
    <p>We may also disclose information if the law requires it, to protect our rights or users, or as part of a sale or reorganisation of our business.</p>

    <h2>5. Retention</h2>
    <p>We keep your account information while your account is open and for a reasonable period afterwards for legal, tax and security reasons. Billing records are kept as required by law. You can delete your investor profile answers at any time by clearing them, or ask us to delete your account.</p>

    <h2>6. Your choices and rights</h2>
    <ul>
      <li>Update your profile and email-alert choices on your profile page; unsubscribe from any opportunity email with one click.</li>
      <li>Ask us for a copy of your personal information, to correct it, or to delete your account, by emailing <Mail/>.</li>
      <li>Depending on where you live (for example California), you may have additional rights, such as to know what we collect and to not be discriminated against for using your rights. We will honour requests as the law requires.</li>
    </ul>

    <h2>7. Security</h2>
    <p>We use encryption in transit, access controls and the security features of our providers. No system is completely secure, so please use a strong, unique password.</p>

    <h2>8. Children</h2>
    <p>The service is for adults. We do not knowingly collect information from anyone under 18.</p>

    <h2>9. Changes to this policy</h2>
    <p>We will post updates here with a new effective date and notify you of material changes by email or in the service.</p>

    <h2>10. Contact</h2>
    <p>{company}, {LEGAL.postalAddress}. Email: <Mail/>.</p>
  </LegalLayout>;
}
