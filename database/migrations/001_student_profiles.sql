
USE db_actrace;

CREATE TABLE IF NOT EXISTS student_profiles (
    profile_id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL UNIQUE,

    -- ACADEMIC INFORMATION
    school_name VARCHAR(150) DEFAULT NULL,
    class_name VARCHAR(50) DEFAULT NULL,
    major VARCHAR(100) DEFAULT NULL,
    academic_year VARCHAR(20) DEFAULT NULL,

    -- INTERNSHIP INFORMATION
    internship_company VARCHAR(150) DEFAULT NULL,
    internship_industry VARCHAR(100) DEFAULT NULL,
    internship_address VARCHAR(255) DEFAULT NULL,

    supervisor_name VARCHAR(100) DEFAULT NULL,
    supervisor_position VARCHAR(100) DEFAULT NULL,

    internship_start_date DATE DEFAULT NULL,
    internship_end_date DATE DEFAULT NULL,

    -- TIMESTAMPS
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    -- RELATIONSHIP
    CONSTRAINT fk_student_profiles_users
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);