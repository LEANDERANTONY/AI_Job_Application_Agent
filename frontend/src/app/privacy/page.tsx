import Link from "next/link";

const EFFECTIVE_DATE = "April 24, 2026";

export default function PrivacyPage() {
  return (
    <div className="app-shell">
      <div className="bg-orb bg-orb-one" />
      <div className="bg-orb bg-orb-two" />

      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">AJ</div>
          <div>
            <p className="brand-title">Job Application Copilot</p>
          </div>
        </div>
        <nav className="nav-links" aria-label="Privacy navigation">
          <Link className="nav-link" href="/">
            Home
          </Link>
        </nav>
      </header>

      <main className="page-frame policy-page-frame">
        <section className="surface-card policy-shell">
          <p className="eyebrow">Privacy Policy</p>
          <h1 className="policy-title">Job Application Copilot</h1>
          <p className="policy-intro">
            Job Application Copilot is built to help users upload resumes,
            review job descriptions, run grounded application analysis, and
            generate tailored application materials in one workspace. This
            Privacy Policy explains what information we collect, how we use it,
            and how we handle it when you use the service.
          </p>
          <p className="policy-effective">Effective date: {EFFECTIVE_DATE}</p>

          <div className="policy-sections">
            <section className="policy-section">
              <h2>Information we collect</h2>
              <p>
                When you sign in with Google, we may receive basic account
                information such as your name, email address, profile image,
                and a unique account identifier. We use this information only
                to authenticate you and connect you to your private workspace.
              </p>
              <p>
                When you upload a resume or provide a job description, Job
                Application Copilot may process the file or text so the app can
                review the role, prepare a candidate snapshot, generate
                tailored outputs, and maintain your saved workspace. This may
                include storing uploaded files, extracted text, structured role
                summaries, generated application materials, saved jobs,
                workspace prompts, and other content needed to make the product
                work as expected.
              </p>
            </section>

            <section className="policy-section">
              <h2>How we use information</h2>
              <p>
                We use information you provide to operate the app, maintain
                your workspace, restore saved state, process uploads, generate
                tailored outputs, support grounded assistant responses, improve
                reliability and security, and prevent misuse.
              </p>
              <p>
                We may also collect limited technical information needed to run
                the service reliably and securely, such as request timestamps,
                session details, error logs, and basic browser or device
                information. We do not sell your personal information, and we
                do not use Google account data for advertising.
              </p>
            </section>

            <section className="policy-section">
              <h2>Google sign-in and account access</h2>
              <p>
                If you sign in with Google, we use Google user data only for
                authentication and account access. We do not access Gmail,
                Google Drive, Google Calendar, or any other Google account
                content unless that is clearly described and separately
                authorized in the future.
              </p>
            </section>

            <section className="policy-section">
              <h2>Third-party services and processing</h2>
              <p>
                To deliver the service, data may be processed and stored using
                third-party infrastructure that supports authentication,
                hosting, storage, retrieval, and model inference. This may
                include providers used for application hosting, authentication,
                data storage, document generation, and AI-assisted processing.
              </p>
              <p>
                Uploaded content and workspace data may be stored temporarily or
                for a limited active-workspace period, depending on how the
                service is configured.
              </p>
            </section>

            <section className="policy-section">
              <h2>Sharing and retention</h2>
              <p>
                We may share information only when necessary to operate the app,
                comply with legal obligations, respond to lawful requests, or
                protect the rights, security, and integrity of Job Application
                Copilot and its users.
              </p>
              <p>
                We keep information only for as long as it is needed to operate
                the service, maintain active workspaces, meet security needs,
                comply with legal obligations, and resolve disputes. Some
                workspace data may be deleted automatically after a period of
                inactivity or expiration.
              </p>
            </section>

            <section className="policy-section">
              <h2>Your choices</h2>
              <p>
                You can choose not to sign in or not to upload files, but some
                features of Job Application Copilot may not work without
                authentication or workspace inputs.
              </p>
              <p>
                If you want to ask about your data or request deletion of
                account-linked information, contact{" "}
                <a className="policy-inline-link" href="mailto:antony.leander@gmail.com">
                  antony.leander@gmail.com
                </a>
                .
              </p>
            </section>

            <section className="policy-section">
              <h2>Security, children, and updates</h2>
              <p>
                We use reasonable technical and organizational measures to
                protect information, but no system can guarantee complete
                security.
              </p>
              <p>
                Job Application Copilot is not intended for children under 13,
                and we do not knowingly collect personal information from
                children under 13.
              </p>
              <p>
                We may update this Privacy Policy from time to time. If we make
                important changes, we will update the effective date and publish
                the revised version on this page.
              </p>
            </section>

            <section className="policy-section">
              <h2>Contact</h2>
              <p>
                If you have any questions about this Privacy Policy or how Job
                Application Copilot handles data, contact{" "}
                <a className="policy-inline-link" href="mailto:antony.leander@gmail.com">
                  antony.leander@gmail.com
                </a>
                .
              </p>
            </section>
          </div>
        </section>
      </main>
    </div>
  );
}
