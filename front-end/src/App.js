import './App.css';
import Navbar from './Navbar';
import Uploadpage from './Uploadpage';
import Homepage from './Homepage';
import UserGuidepage from './UserGuidepage';
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";


function App() {
  return (
    <Router>
      <div className="App">
        <Navbar />
        <div className="content">
          <Routes>
            <Route path="/" element={<Homepage />} />
            <Route path="/upload" element={<Uploadpage />} />
            <Route path="/userguide" element={<UserGuidepage />} />
          </Routes>
        </div>
      </div>
    </Router>
  );
}

export default App;
