
import step1 from "./step1.png";
import step2 from "./step2.png";
import step3 from "./step3.png";
import step4 from "./step4.png";

const UserGuidepage = () => {
    return(
        <div className="userguidepage" style={{textAlign: "left", padding: "16px"}}>
            <h2>User Guide Page</h2>
            <h3 style={{padding: "16px"}}>Follow the instructions below:</h3>
            <p style={{padding: "16px"}}><strong>Step 1:</strong> When you want to process a medical bill click on Upload Bills.</p>
            <img src={step1} alt="Step 1" style={{width: "300px", margin: "16px", borderRadius: "8px", boxShadow: "0px 4px 12px rgba(0, 0, 0, 0.15)"}} />
            <p style={{padding: "16px"}}><strong>Step 2:</strong> Click on the 'Upload Bill' button and select your file.</p>
            <img src={step2} alt="Step 2" style={{width: "300px", margin: "16px", borderRadius: "8px", boxShadow: "0px 4px 12px rgba(0, 0, 0, 0.15)"}} />
            <p style={{padding: "16px"}}><strong>Step 3:</strong> Wait until your medical bill has been processed.</p>
            <img src={step3} alt="Step 3" style={{width: "300px", margin: "16px", borderRadius: "8px", boxShadow: "0px 4px 12px rgba(0, 0, 0, 0.15)"}} />
            <p style={{padding: "16px"}}><strong>Step 4:</strong> When the medical bill has been processed you'll see the results being displayed.</p>
            <img src={step4} alt="Step 4" style={{width: "300px", margin: "16px", borderRadius: "8px", boxShadow: "0px 4px 12px rgba(0, 0, 0, 0.15)"}} />
            <h4>Information about the results:</h4>
            <p>Covered: This means the medical bill is covered by insurance policy and the amount covered will be given in the table</p>
            <p>Not Covered: This means that the medical bill is not covered by the insurance policy</p>
            <p>NOTE: If the bill has the wrong procedural and diagnosis codes the system will not adjudicate the bill and it will return an invalid medical bill message</p>
            <p>If that happens you have to resubmit the correct medical bill</p>


        </div>
    );

}


export default UserGuidepage;