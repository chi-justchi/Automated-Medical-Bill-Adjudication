
import { Link } from "react-router-dom";
import "./Navbar.css";


const Navbar = () => {
    return (
        <nav className="navbar" style={{ backgroundColor: '#333333', padding: '1rem', color: 'white', boxShadow: "0 4px 8px rgba(0,0,0,0.3)"}}>
            <h1>Medical Bill Adjudication System</h1>
            <div className="links">
                <Link to="/" style={{ color: 'white', marginLeft: '1rem', textDecoration: "none"}}>Home</Link>
                <Link to="/upload" style={{ color: 'white', marginLeft: '1rem', textDecoration: "none"}}>Upload Bills</Link>
                <Link to="/userguide" style={{ color: 'white', marginLeft: '1rem', textDecoration: "none"}}>User Guide</Link>
            </div>
        </nav>
    );
}

export default Navbar;