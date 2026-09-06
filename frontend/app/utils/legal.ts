/**
 * The legal pages, held as markup rather than as Vue templates.
 *
 * Nego-lah is an SPA (`ssr: false`), so a crawler that fetches
 * https://negolah.my/privacy receives the empty app shell and sees no policy at
 * all — which is exactly why Google's OAuth verification rejected the page for
 * not having "sufficient content". Keeping the text here lets the same string
 * be rendered two ways from ONE source: the Vue page renders it for people, and
 * `nitro:init` in nuxt.config injects it into the prerendered HTML for crawlers.
 *
 * Duplicating the text into a second static file instead would let the version
 * users read drift away from the version Google reviews, so don't.
 */
export interface LegalDocument {
  title: string
  description: string
  lastUpdated: string
  /** The document body: `<section>` blocks, no page heading. */
  body: string
}

const H2 = 'text-xl font-semibold text-highlighted'
const UL = 'list-disc pl-6 space-y-1'
const LINK = 'text-primary'

export const PRIVACY_POLICY: LegalDocument = {
  title: 'Privacy Policy',
  description: 'How Nego-lah collects, uses, shares, retains and protects your personal information, including the data received from Google when you sign in with Google.',
  lastUpdated: '6 September 2026',
  body: `
<section class="space-y-2">
  <h2 class="${H2}">1. Introduction</h2>
  <p>
    Nego-lah ("we", "us", "our") operates negolah.my, a second-hand marketplace where
    buyers negotiate the price of a listing with an AI seller before checking out. This
    policy explains what personal data we collect, why we collect it, who we share it
    with, how long we keep it, and the rights and choices you have over it.
  </p>
  <p>
    It applies to the negolah.my website and to every account created on it, whether you
    sign up with an email address and password or with Google. By using Nego-lah you
    agree to the handling of your information described here.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">2. Information We Collect</h2>
  <p>We collect only what the marketplace needs in order to work.</p>
  <ul class="${UL}">
    <li>
      <strong>Account and sign-in data.</strong> Your email address, and either a password
      (stored only as a salted hash by our authentication provider, never in readable
      form) or a link to your Google account if you sign in with Google. We also store
      your language preference and the timestamps of account creation and last sign-in.
    </li>
    <li>
      <strong>Data received from Google.</strong> If you choose "Sign in with Google", we
      receive your name, email address, profile picture and Google account identifier.
      Section 4 sets out exactly how that data is used.
    </li>
    <li>
      <strong>Profile data.</strong> A display name and, optionally, a profile picture you
      upload. An uploaded picture is stored in our own file storage, separately from the
      picture supplied by Google.
    </li>
    <li>
      <strong>Negotiation and chat content.</strong> The messages you send to the AI
      seller, the offers exchanged, the price agreed and the listing each conversation
      relates to. Section 5 describes the AI processing involved.
    </li>
    <li>
      <strong>Order and payment data.</strong> The items you buy, the amount paid, the
      order status and the payment confirmation returned by our payment processor.
      <strong>We never receive or store your full card number, expiry date or security
      code</strong> — those go directly to the payment processor.
    </li>
    <li>
      <strong>Technical and diagnostic data.</strong> Your IP address, browser and device
      type, the pages you open and, when something goes wrong, error reports and
      performance traces. A small randomly sampled share of sessions, plus sessions in
      which an error occurs, are recorded as session replays; in production those replays
      mask all text and form input and block images and video, so they capture layout and
      interaction rather than the content you type.
    </li>
    <li><strong>Cookies and local storage.</strong> See section 7.</li>
  </ul>
  <p>
    We do not collect government identification numbers, precise location, or any special
    category data such as health, biometric or political information.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">3. How We Use Your Information</h2>
  <ul class="${UL}">
    <li>To create your account, sign you in and keep your session secure.</li>
    <li>To show you your profile, listings, conversations and order history.</li>
    <li>To run AI-assisted price negotiations and generate the AI seller's replies.</li>
    <li>To take payment, fulfil orders and issue receipts.</li>
    <li>
      To send transactional email you would expect: purchase receipts, negotiation and
      hand-over notifications, password resets and email confirmations.
    </li>
    <li>
      To detect and prevent fraud, automated abuse and breaches of our terms, and to
      enforce account bans.
    </li>
    <li>To diagnose crashes and performance problems and keep the service reliable.</li>
    <li>To understand in aggregate how the marketplace is used so we can improve it.</li>
    <li>To comply with legal, accounting and tax obligations.</li>
  </ul>
  <p>
    We do not use your personal data to make automated decisions producing legal effects
    about you, and we do not sell it or use it for third-party advertising.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">4. Google User Data</h2>
  <p>
    Signing in with Google is optional — an email address and password work just as well.
    If you do use it, Google asks for your consent and then sends us a limited set of
    information from your Google account:
  </p>
  <ul class="${UL}">
    <li>
      <strong>Your email address</strong> — used as your account identifier, to sign you
      in, and to send you transactional email.
    </li>
    <li>
      <strong>Your name</strong> — used as the default display name on your profile and in
      negotiations.
    </li>
    <li>
      <strong>Your profile picture</strong> — displayed as your avatar. If you later upload
      your own picture, that one is used instead and is stored under a separate key, so a
      later Google sign-in cannot overwrite it.
    </li>
    <li>
      <strong>Your Google account identifier</strong> — used solely to recognise your
      account on the next sign-in.
    </li>
  </ul>
  <p>
    We request only the basic <code>openid</code>, <code>email</code> and
    <code>profile</code> scopes. We do not request access to Gmail, Drive, Calendar,
    Contacts, Photos or any other Google service, and we cannot read, create or modify
    anything in your Google account.
  </p>
  <p>
    <strong>Limited Use.</strong> Nego-lah's use of information received from Google APIs
    adheres to the
    <a class="${LINK}" href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer">Google
    API Services User Data Policy</a>, including the Limited Use requirements. We use
    Google user data only to provide and improve the user-facing features described above.
    We do not transfer it to third parties except as necessary to provide those features
    (see section 6), to comply with applicable law, or as part of a merger or acquisition.
    We do not sell Google user data, we do not use it for advertising, and we do not use it
    to develop, improve or train generalised artificial intelligence or machine learning
    models. No human reads your Google user data except with your explicit consent, where
    it is necessary for security purposes such as investigating abuse, or where the law
    requires it.
  </p>
  <p>
    You can withdraw Nego-lah's access to your Google account at any time from
    <a class="${LINK}" href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer">your
    Google account permissions page</a>. That stops future Google sign-ins; to remove the
    data already held, delete your Nego-lah account as described in section 10.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">5. AI Processing of Your Conversations</h2>
  <p>
    Price negotiation on Nego-lah is performed by a large language model. The message you
    send, the recent history of that conversation and details of the listing being
    negotiated are sent to the model so that it can reply. Listing images may be analysed
    the same way.
  </p>
  <p>
    That processing normally happens on a model we host ourselves. When our own model is
    unavailable the request fails over to Google's Gemini API, and the same conversation
    content is processed by Google under
    <a class="${LINK}" href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">Google's
    privacy policy</a> and its API terms. Please do not put sensitive personal
    information, passwords or payment details into a negotiation chat — it is not the
    right place for them.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">6. How We Share Information</h2>
  <p>
    <strong>We do not sell your personal data and we do not share it for advertising.</strong>
    We share it only with the service providers that make the marketplace work, each acting
    on our instructions and only for the purpose listed:
  </p>
  <ul class="${UL}">
    <li><strong>Supabase</strong> — authentication, database and file storage for your account, profile picture and negotiation history.</li>
    <li><strong>Google (Sign-In)</strong> — verifies your identity when you choose "Sign in with Google" and returns your basic Google profile.</li>
    <li><strong>Google (Gemini API)</strong> — generates AI negotiation replies and analyses listing images when our own model is unavailable.</li>
    <li><strong>Google Analytics</strong> — aggregate, pseudonymous usage statistics showing which parts of the marketplace are used.</li>
    <li><strong>Stripe</strong> — processes card payments and returns the payment outcome; Stripe receives your payment details directly.</li>
    <li><strong>Cloudflare</strong> — hosts and delivers the website and runs the Turnstile check that blocks automated abuse.</li>
    <li><strong>Sentry</strong> — collects crash reports, performance traces and sampled session replays so we can diagnose faults.</li>
    <li><strong>Resend</strong> — delivers transactional email such as purchase receipts and negotiation notifications.</li>
  </ul>
  <p>
    Other buyers and sellers see only what you make public: your display name, your profile
    picture, and the listings and offers you take part in. Your email address is never
    shown to another user.
  </p>
  <p>
    We may also disclose information where we are legally required to, where it is
    necessary to investigate fraud or protect someone's safety, or to a successor entity in
    a merger or acquisition — in which case this policy continues to apply to the
    transferred data.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">7. Cookies and Local Storage</h2>
  <p>We use browser cookies and local storage for a small number of purposes:</p>
  <ul class="${UL}">
    <li>
      <strong>Strictly necessary</strong> — to hold your signed-in session and the security
      token that keeps it valid, and to run the Cloudflare Turnstile check that blocks
      automated abuse. The site cannot function without these.
    </li>
    <li><strong>Preferences</strong> — to remember your chosen language and colour theme.</li>
    <li>
      <strong>Analytics and diagnostics</strong> — to attribute page views and error reports
      to a single pseudonymous session.
    </li>
  </ul>
  <p>
    You can clear or block cookies in your browser settings, but blocking the strictly
    necessary ones will sign you out and prevent checkout.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">8. International Transfers</h2>
  <p>
    Nego-lah is operated from Malaysia, and the providers listed in section 6 operate
    globally. Your information may therefore be stored or processed on servers outside your
    country, including in the United States and the European Union. Where that happens we
    rely on those providers' contractual data-protection commitments, such as standard
    contractual clauses, to protect the transfer.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">9. How Long We Keep Your Data</h2>
  <ul class="${UL}">
    <li>
      <strong>Account, profile and negotiation history</strong> — kept while your account is
      open and deleted when you delete your account.
    </li>
    <li>
      <strong>Order and payment records</strong> — retained after account deletion, because
      we are required to keep business, accounting and tax records. They are no longer
      linked to a usable account.
    </li>
    <li>
      <strong>Diagnostic data, error reports and session replays</strong> — retained by our
      monitoring provider on a rolling window (currently 90 days or less) and then removed
      automatically.
    </li>
    <li><strong>Aggregate analytics</strong> — retained in a form that no longer identifies you.</li>
  </ul>
</section>

<section class="space-y-2">
  <h2 class="${H2}">10. Your Rights and Choices</h2>
  <p>You can do all of the following at any time:</p>
  <ul class="${UL}">
    <li>
      <strong>Access and correct</strong> your account details, display name, avatar, email
      address and password from your <a class="${LINK}" href="/profile">profile settings</a>.
    </li>
    <li>
      <strong>Delete your account.</strong> "Delete account" in your profile settings
      permanently removes your sign-in credentials, profile, chat settings and negotiation
      conversations. Order records are retained as described in section 9. The deletion
      cannot be undone.
    </li>
    <li>
      <strong>Withdraw Google access</strong> from your
      <a class="${LINK}" href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer">Google
      account permissions page</a>.
    </li>
    <li>
      <strong>Request a copy</strong> of the personal data we hold about you, or ask us to
      restrict or object to a particular use, by emailing us.
    </li>
    <li>
      <strong>Complain</strong> to your local data-protection authority if you believe we
      have handled your data improperly.
    </li>
  </ul>
  <p>We respond to requests sent to the address in section 13 within 30 days.</p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">11. Security</h2>
  <p>
    All traffic to negolah.my and to our API is encrypted in transit with HTTPS. Passwords
    are stored only as salted hashes. Database access is restricted by row-level security
    policies so that one account cannot read another's data, and administrative access is
    limited to the operator of the service. Card details never touch our servers. Automated
    sign-up and sign-in abuse is filtered by Cloudflare Turnstile.
  </p>
  <p>
    No online service can promise perfect security. If a breach affects your personal data
    we will notify you and the relevant authority as required by law.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">12. Children</h2>
  <p>
    Nego-lah involves payment for goods and is not intended for children. You must be at
    least 18 years old, or the age of majority where you live, to create an account. We do
    not knowingly collect personal data from children; if you believe a child has given us
    their information, contact us and we will delete it.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">13. Changes and Contact</h2>
  <p>
    If we change this policy we will update the "last updated" date above, and for material
    changes we will notify you by email or with a notice in the app before the change takes
    effect.
  </p>
  <p>
    Questions, requests or complaints about this policy or your data can be sent to
    <a class="${LINK}" href="mailto:support@negolah.my">support@negolah.my</a>. You can also
    read our <a class="${LINK}" href="/terms">Terms of Service</a>.
  </p>
</section>
`
}

export const TERMS_OF_SERVICE: LegalDocument = {
  title: 'Terms of Service',
  description: 'The terms and conditions for using the Nego-lah marketplace.',
  lastUpdated: '6 September 2026',
  body: `
<section class="space-y-2">
  <h2 class="${H2}">1. Acceptance of Terms</h2>
  <p>
    By accessing or using Nego-lah, you agree to be bound by these Terms of Service. If you
    do not agree, please do not use the service.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">2. Your Account</h2>
  <p>
    You are responsible for keeping your login credentials secure and for all activity under
    your account. You must provide accurate information and be at least the age of majority
    in your jurisdiction.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">3. Negotiations and Pricing</h2>
  <p>
    Prices on Nego-lah are negotiated with an AI seller. Any price agreed during a
    negotiation is an offer to transact; final sale is subject to availability and
    successful payment. We reserve the right to correct pricing errors.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">4. Orders and Payment</h2>
  <p>
    When you complete checkout you agree to pay the agreed amount. Payments are handled by
    our payment partners. Orders may be cancelled if payment fails or if the item is no
    longer available.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">5. Acceptable Use</h2>
  <ul class="${UL}">
    <li>Do not use the service for any unlawful or fraudulent purpose.</li>
    <li>Do not attempt to disrupt, reverse engineer, or abuse the AI or platform.</li>
    <li>Do not misrepresent items, prices, or your identity.</li>
  </ul>
</section>

<section class="space-y-2">
  <h2 class="${H2}">6. Disclaimer</h2>
  <p>
    The service is provided "as is" without warranties of any kind. We do not guarantee
    uninterrupted availability or that AI-generated responses are error-free.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">7. Limitation of Liability</h2>
  <p>
    To the maximum extent permitted by law, Nego-lah is not liable for any indirect,
    incidental, or consequential damages arising from your use of the service.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">8. Changes to These Terms</h2>
  <p>
    We may update these terms from time to time. Continued use of the service after changes
    take effect constitutes acceptance of the revised terms.
  </p>
</section>

<section class="space-y-2">
  <h2 class="${H2}">9. Contact</h2>
  <p>
    Questions about these terms? Reach out to
    <a class="${LINK}" href="mailto:support@negolah.my">support@negolah.my</a>. Our
    <a class="${LINK}" href="/privacy">Privacy Policy</a> explains how we handle your data.
  </p>
</section>
`
}

/**
 * The complete page markup for a legal document — heading, date and body.
 *
 * Rendered by the Vue page at runtime and injected into the prerendered HTML at
 * build time, so both audiences read byte-identical text.
 */
export function renderLegalDocument(doc: LegalDocument): string {
  return `<div class="max-w-3xl mx-auto py-8">`
    + `<h1 class="text-3xl font-bold text-highlighted">${doc.title}</h1>`
    + `<p class="text-sm text-muted mt-2">Last updated: ${doc.lastUpdated}</p>`
    + `<div class="prose dark:prose-invert mt-8 space-y-6 text-toned">${doc.body}</div>`
    + `</div>`
}
