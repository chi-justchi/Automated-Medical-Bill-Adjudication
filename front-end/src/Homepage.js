

const Homepage = () => {
    return(
        <div className="homepage" style={{ textAlign: "left", padding: "16px" }}>
            <h2>Home Page</h2>
            <h3 style={{borderBottom: "1px solid black", width: "100%", paddingBottom: "8px"}}>Automated Medical Bill Adjudication System</h3>
            <p style={{ maxWidth: "700px" }}>
                Welcome and Thank you for using our service: Automated Medical Bill Adjudication System - presented by Team 9.

                <br /> <br /> <br /> <br />
                The aim of this system is to decrease medical bill adjudication time by leveraging Artificial Intelligence so both insurance companies and patients can benefit from faster results.
                
                <br /><br />
                
                How to use:
                This website has 3 pages - you are currently at the Home page.
                You can navigate between the pages: 'Home', 'Upload Bills', and 'User Guide' from the header of the pages.
                <br /><br />
                Look at the User Guide page to know the step by step process on how to use our system.
                <br /><br />
                Once you know how to use this, navigate to the Upload Bills page to upload your medical bill.
                <br /><br />
                Happy Adjudicating!


                
                
            </p>
        </div>
    );


}




export default Homepage;


